from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, UserRole
from backend.app.models.location import Location
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.air_quality import AirQualityReading, QualityStatus

# Isolated in-memory SQLite database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)

admin_token = ""
analyst_token = ""
viewer_token = ""
test_loc_id = 0
test_source_id = 0


@pytest.fixture(autouse=True)
def setup_phase3_db():
    global admin_token, analyst_token, viewer_token, test_loc_id, test_source_id
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Create test users with distinct roles
    admin = User(
        username="admin_p3",
        email="admin_p3@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_p3",
        email="analyst_p3@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_p3",
        email="viewer_p3@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Create baseline Location and DataSource
    loc = Location(
        name="Test Sensor Alpha",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
        description="Core test location",
        is_active=True,
    )
    db.add(loc)

    ds = DataSource(
        name="Test API Stream",
        source_type=SourceType.API,
        provider="Test Provider Inc.",
        description="Automated synthetic API",
        is_active=True,
    )
    db.add(ds)
    db.commit()

    test_loc_id = loc.id
    test_source_id = ds.id
    db.close()

    # Fetch tokens
    admin_token = client.post("/api/v1/auth/login", json={"username": "admin_p3", "password": "AdminPass123!"}).json()["access_token"]
    analyst_token = client.post("/api/v1/auth/login", json={"username": "analyst_p3", "password": "AnalystPass123!"}).json()["access_token"]
    viewer_token = client.post("/api/v1/auth/login", json={"username": "viewer_p3", "password": "ViewerPass123!"}).json()["access_token"]

    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.pop(get_db, None)


# TEST 1: Location creation (Admin)
def test_location_creation():
    response = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Delhi Connaught Place",
            "city": "Delhi",
            "state": "Delhi",
            "country": "India",
            "latitude": 28.6315,
            "longitude": 77.2167,
            "description": "Central commercial monitoring node",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Delhi Connaught Place"
    assert data["city"] == "Delhi"
    assert "id" in data


# TEST 2: Location validation (Latitude and Longitude limits)
def test_location_validation():
    # Invalid latitude > 90
    res1 = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "North Pole Out Of Bounds",
            "city": "Arctic",
            "state": "Global",
            "latitude": 95.0,
            "longitude": 0.0,
        },
    )
    assert res1.status_code == 422

    # Invalid longitude < -180
    res2 = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "West Bounds Beyond Limits",
            "city": "Pacific",
            "state": "Global",
            "latitude": 0.0,
            "longitude": -195.0,
        },
    )
    assert res2.status_code == 422


# TEST 3: Data source creation (Admin)
def test_data_source_creation():
    response = client.post(
        "/api/v1/data-sources",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Upload CSV Service",
            "source_type": "UPLOADED",
            "provider": "User File Intake",
            "description": "Intake for manual tabular uploads",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Upload CSV Service"
    assert data["source_type"] == "UPLOADED"


# TEST 4: Air-quality reading creation
def test_air_quality_reading_creation():
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 45.2,
            "pm10": 85.0,
            "co": 0.9,
            "no2": 32.5,
            "so2": 11.0,
            "o3": 28.0,
            "temperature": 26.5,
            "humidity": 55.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["pm25"] == 45.2
    assert data["pm10"] == 85.0
    assert data["quality_status"] == "VALID"


# TEST 5: Missing pollutant values MUST remain NULL (Never 0!)
def test_missing_pollutants_remain_null():
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 55.0,
            "pm10": None,  # Explicitly None
            "co": None,    # Explicitly None
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["pm25"] == 55.0
    # Must be None / null, NOT 0.0!
    assert data["pm10"] is None
    assert data["co"] is None
    assert data["so2"] is None


# TEST 6: Negative pollutant rejection/quality handling (Flagged as INVALID)
def test_negative_pollutant_quality_triage():
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": -15.0,  # Physically impossible negative concentration
            "pm10": 40.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["quality_status"] == "INVALID"
    assert "Negative PM2.5" in data["validation_notes"]


# TEST 7: Humidity validation (0-100%)
def test_humidity_validation():
    now = datetime.now(timezone.utc)
    # Pydantic rejects >100% on input schema
    res = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 30.0,
            "humidity": 125.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert res.status_code == 422


# TEST 8: Duplicate reading detection
def test_duplicate_reading_detection():
    fixed_time = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    payload = {
        "location_id": test_loc_id,
        "timestamp": fixed_time,
        "pm25": 40.0,
        "source_id": test_source_id,
        "source_type": "API",
    }
    # First submission -> 201 Created
    res1 = client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json=payload)
    assert res1.status_code == 201

    # Second identical submission -> 409 Conflict
    res2 = client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json=payload)
    assert res2.status_code == 409
    assert "Duplicate reading detected" in res2.json()["detail"]


# TEST 9: Current reading endpoint
def test_current_reading_endpoint():
    t1 = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 18, 11, 0, 0, tzinfo=timezone.utc)

    client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"location_id": test_loc_id, "timestamp": t1.isoformat(), "pm25": 30.0, "source_id": test_source_id, "source_type": "API"},
    )
    client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"location_id": test_loc_id, "timestamp": t2.isoformat(), "pm25": 99.0, "source_id": test_source_id, "source_type": "API"},
    )

    response = client.get(
        f"/api/v1/air-quality/current?location_id={test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["location_id"] == test_loc_id
    assert data["reading"]["pm25"] == 99.0  # Most recent reading


# TEST 10: Historical reading endpoint
def test_historical_reading_endpoint():
    base_t = datetime(2026, 9, 18, 8, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        client.post(
            "/api/v1/air-quality/readings",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={
                "location_id": test_loc_id,
                "timestamp": (base_t + timedelta(hours=i)).isoformat(),
                "pm25": float(20 + i * 5),
                "source_id": test_source_id,
                "source_type": "API",
            },
        )

    response = client.get(
        f"/api/v1/air-quality/history?location_id={test_loc_id}&limit=3",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


# TEST 11: Location filtering
def test_location_filtering():
    # Create second location
    loc2 = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Mumbai Bandra Station", "city": "Mumbai", "state": "Maharashtra", "latitude": 19.05, "longitude": 72.84},
    ).json()

    now = datetime.now(timezone.utc).isoformat()
    client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json={"location_id": test_loc_id, "timestamp": now, "pm25": 40.0, "source_id": test_source_id, "source_type": "API"})
    client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json={"location_id": loc2["id"], "timestamp": now, "pm25": 80.0, "source_id": test_source_id, "source_type": "API"})

    # Query only location 2
    res = client.get(f"/api/v1/air-quality/history?location_id={loc2['id']}", headers={"Authorization": f"Bearer {viewer_token}"})
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["location_id"] == loc2["id"]
    assert items[0]["pm25"] == 80.0


# TEST 12: Time-range filtering
def test_time_range_filtering():
    t_start = datetime(2026, 9, 10, 10, 0, 0, tzinfo=timezone.utc)
    t_mid = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    t_end = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)

    client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json={"location_id": test_loc_id, "timestamp": t_start.isoformat(), "pm25": 25.0, "source_id": test_source_id, "source_type": "API"})
    client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json={"location_id": test_loc_id, "timestamp": t_mid.isoformat(), "pm25": 50.0, "source_id": test_source_id, "source_type": "API"})
    client.post("/api/v1/air-quality/readings", headers={"Authorization": f"Bearer {analyst_token}"}, json={"location_id": test_loc_id, "timestamp": t_end.isoformat(), "pm25": 75.0, "source_id": test_source_id, "source_type": "API"})

    # Filter window containing only t_mid
    filter_start = datetime(2026, 9, 11, 0, 0, 0, tzinfo=timezone.utc).isoformat()
    filter_end = datetime(2026, 9, 13, 0, 0, 0, tzinfo=timezone.utc).isoformat()

    res = client.get(
        "/api/v1/air-quality/history",
        params={
            "location_id": test_loc_id,
            "start_time": filter_start,
            "end_time": filter_end,
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["pm25"] == 50.0


# TEST 13: Source/provenance preservation
def test_source_provenance_preservation():
    now = datetime.now(timezone.utc).isoformat()
    response = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now,
            "pm25": 60.0,
            "source_id": test_source_id,
            "source_type": "SIMULATED",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "SIMULATED"


# TEST 14: RBAC for location/data-source management
def test_rbac_location_datasource_management():
    # Viewer cannot create a location
    res_viewer = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"name": "Forbidden Station", "city": "Bengaluru", "state": "Karnataka", "latitude": 12.9, "longitude": 77.6},
    )
    assert res_viewer.status_code == 403

    # Analyst cannot create a location (Admin only)
    res_analyst = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={"name": "Forbidden Station 2", "city": "Bengaluru", "state": "Karnataka", "latitude": 12.9, "longitude": 77.6},
    )
    assert res_analyst.status_code == 403

    # Viewer cannot create a data source (Admin only)
    res_ds_viewer = client.post(
        "/api/v1/data-sources",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"name": "Forbidden Source", "source_type": "API"},
    )
    assert res_ds_viewer.status_code == 403


# TEST 15: Unauthorized access rejection (No Token)
def test_unauthorized_access_rejection():
    res1 = client.get("/api/v1/locations")
    assert res1.status_code == 401

    res2 = client.get("/api/v1/data-sources")
    assert res2.status_code == 401

    res3 = client.get("/api/v1/air-quality/current?location_id=1")
    assert res3.status_code == 401

    res4 = client.get("/api/v1/air-quality/history")
    assert res4.status_code == 401
