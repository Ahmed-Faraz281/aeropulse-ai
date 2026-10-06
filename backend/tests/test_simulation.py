from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, UserRole
from backend.app.models.location import Location
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.schemas.simulation import SimulationScenario

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
loc1_id = 0
loc2_id = 0


@pytest.fixture(autouse=True)
def setup_simulation_test_db():
    global admin_token, analyst_token, viewer_token, loc1_id, loc2_id
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Create users
    admin = User(
        username="admin_sim",
        email="admin_sim@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_sim",
        email="analyst_sim@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_sim",
        email="viewer_sim@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Login and acquire tokens
    res_admin = client.post("/api/v1/auth/login", data={"username": "admin_sim", "password": "AdminPass123!"})
    admin_token = res_admin.json()["access_token"]

    res_analyst = client.post("/api/v1/auth/login", data={"username": "analyst_sim", "password": "AnalystPass123!"})
    analyst_token = res_analyst.json()["access_token"]

    res_viewer = client.post("/api/v1/auth/login", data={"username": "viewer_sim", "password": "ViewerPass123!"})
    viewer_token = res_viewer.json()["access_token"]

    # Seed monitored locations
    loc1 = Location(
        name="MG Road Station",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
        is_active=True,
    )
    loc2 = Location(
        name="Connaught Place",
        city="Delhi",
        state="Delhi",
        country="India",
        latitude=28.6315,
        longitude=77.2167,
        is_active=True,
    )
    db.add_all([loc1, loc2])
    db.commit()
    db.refresh(loc1)
    db.refresh(loc2)
    loc1_id = loc1.id
    loc2_id = loc2.id

    db.close()
    yield
    # Teardown
    Base.metadata.drop_all(bind=test_engine)


def test_simulation_normal_execution():
    """Verify standard simulation execution, counts, and SIMULATED provenance."""
    payload = {
        "location_ids": [loc1_id],
        "duration_hours": 6,
        "interval_minutes": 60,
        "scenario": "NORMAL",
        "intensity": 1.0,
        "seed": 42,
    }
    response = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["source_type"] == "SIMULATED"
    assert data["locations"] == 1
    assert data["readings_generated"] == 7  # 6h with 60m interval = 7 steps
    assert data["readings_inserted"] == 7
    assert data["readings_skipped"] == 0
    assert data["scenario"] == "NORMAL"
    assert data["seed"] == 42

    # Verify database persistence
    db = TestingSessionLocal()
    readings = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc1_id).all()
    assert len(readings) == 7
    for r in readings:
        assert r.source_type == SourceType.SIMULATED
        assert r.quality_status == QualityStatus.VALID
        assert r.pm25 > 0
        assert r.pm10 > r.pm25  # PM10 correlated higher than PM2.5

    # Verify AQI pre-caching
    aqi_records = db.query(AQIRecord).filter(AQIRecord.location_id == loc1_id).all()
    assert len(aqi_records) == 7
    for rec in aqi_records:
        assert rec.status == "CALCULATED"
        assert rec.aqi is not None
        assert rec.category in ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    db.close()


def test_simulation_deterministic_seed():
    """Verify that identical parameters with same seed produce identical sequences."""
    payload1 = {
        "location_ids": [loc1_id],
        "duration_hours": 4,
        "interval_minutes": 60,
        "scenario": "NORMAL",
        "intensity": 1.0,
        "seed": 101,
    }
    res1 = client.post(
        "/api/v1/simulation/run",
        json=payload1,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res1.status_code == 200

    db = TestingSessionLocal()
    first_run_readings = [
        (r.pm25, r.no2, r.co)
        for r in db.query(AirQualityReading).order_by(AirQualityReading.timestamp.asc()).all()
    ]
    # Clean up DB for second run
    db.query(AQIRecord).delete()
    db.query(AirQualityReading).delete()
    db.commit()
    db.close()

    # Second run with exact same seed
    res2 = client.post(
        "/api/v1/simulation/run",
        json=payload1,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res2.status_code == 200

    db = TestingSessionLocal()
    second_run_readings = [
        (r.pm25, r.no2, r.co)
        for r in db.query(AirQualityReading).order_by(AirQualityReading.timestamp.asc()).all()
    ]
    assert first_run_readings == second_run_readings

    # Third run with different seed
    db.query(AQIRecord).delete()
    db.query(AirQualityReading).delete()
    db.commit()
    db.close()

    payload_diff = {**payload1, "seed": 999}
    client.post(
        "/api/v1/simulation/run",
        json=payload_diff,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    db = TestingSessionLocal()
    third_run_readings = [
        (r.pm25, r.no2, r.co)
        for r in db.query(AirQualityReading).order_by(AirQualityReading.timestamp.asc()).all()
    ]
    assert first_run_readings != third_run_readings
    db.close()


def test_simulation_scenarios():
    """Verify all simulation scenarios execute without error and produce valid readings."""
    scenarios = [
        SimulationScenario.RISING_POLLUTION,
        SimulationScenario.POLLUTION_SPIKE,
        SimulationScenario.PERSISTENT_ELEVATED,
        SimulationScenario.RECOVERY,
    ]
    for sc in scenarios:
        db = TestingSessionLocal()
        db.query(AQIRecord).delete()
        db.query(AirQualityReading).delete()
        db.commit()
        db.close()

        payload = {
            "location_ids": [loc1_id],
            "duration_hours": 6,
            "interval_minutes": 60,
            "scenario": sc.value,
            "intensity": 1.2,
            "seed": 77,
        }
        res = client.post(
            "/api/v1/simulation/run",
            json=payload,
            headers={"Authorization": f"Bearer {analyst_token}"},
        )
        assert res.status_code == 200
        assert res.json()["scenario"] == sc.value
        assert res.json()["readings_inserted"] == 7


def test_simulation_duplicate_handling():
    """Verify that re-running simulation over existing timestamps skips duplicate records."""
    payload = {
        "location_ids": [loc1_id],
        "duration_hours": 3,
        "interval_minutes": 60,
        "scenario": "NORMAL",
        "seed": 55,
    }
    # First execution
    res1 = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res1.status_code == 200
    assert res1.json()["readings_inserted"] == 4
    assert res1.json()["readings_skipped"] == 0

    # Second execution with exact same timestamp window
    res2 = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res2.status_code == 200
    assert res2.json()["readings_inserted"] == 0
    assert res2.json()["readings_skipped"] == 4


def test_simulation_backend_safety_limit_record_cap():
    """Verify that requests exceeding 1,000 records are rejected with HTTP 400 on backend."""
    # 72 hours * 60 / 15 mins = 289 steps per location. 4 locations = 1,156 records (>1000)
    payload = {
        "location_ids": [loc1_id, loc2_id],
        "duration_hours": 72,
        "interval_minutes": 15,  # 289 * 2 = 578 (within 1000)
    }
    # Let's exceed with 4 locations
    db = TestingSessionLocal()
    loc3 = Location(name="L3", city="C3", state="S3", country="IN", latitude=10, longitude=20)
    loc4 = Location(name="L4", city="C4", state="S4", country="IN", latitude=10, longitude=20)
    db.add_all([loc3, loc4])
    db.commit()
    db.refresh(loc3)
    db.refresh(loc4)
    db.close()

    payload_exceed = {
        "location_ids": [loc1_id, loc2_id, loc3.id, loc4.id],
        "duration_hours": 72,
        "interval_minutes": 15,  # 289 * 4 = 1156 records > 1000!
    }
    res = client.post(
        "/api/v1/simulation/run",
        json=payload_exceed,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 400
    assert "exceeding the maximum safety limit of 1000 records" in res.json()["detail"]


def test_simulation_parameter_validations():
    """Verify input validation rules for invalid duration, interval, intensity, or locations."""
    # Invalid duration (< 1)
    res_dur = client.post(
        "/api/v1/simulation/run",
        json={"location_ids": [loc1_id], "duration_hours": 0, "interval_minutes": 60},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_dur.status_code == 422

    # Invalid interval (< 15)
    res_int = client.post(
        "/api/v1/simulation/run",
        json={"location_ids": [loc1_id], "duration_hours": 12, "interval_minutes": 5},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_int.status_code == 422

    # Invalid intensity (< 0.1 or > 3.0)
    res_intensity = client.post(
        "/api/v1/simulation/run",
        json={"location_ids": [loc1_id], "duration_hours": 12, "interval_minutes": 60, "intensity": 5.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_intensity.status_code == 422

    # Empty location_ids
    res_empty_locs = client.post(
        "/api/v1/simulation/run",
        json={"location_ids": [], "duration_hours": 12, "interval_minutes": 60},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_empty_locs.status_code == 422


def test_simulation_nonexistent_location():
    """Verify that referencing an un-registered location ID returns HTTP 404."""
    payload = {
        "location_ids": [99999],
        "duration_hours": 6,
        "interval_minutes": 60,
    }
    res = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 404
    assert "Location IDs [99999] do not exist" in res.json()["detail"]


def test_simulation_rbac_enforcement():
    """Verify that ADMIN and ANALYST are allowed to execute, whereas VIEWER is denied with HTTP 403."""
    payload = {
        "location_ids": [loc1_id],
        "duration_hours": 2,
        "interval_minutes": 60,
    }

    # Admin: Allowed
    res_admin = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200

    # Analyst: Allowed
    res_analyst = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res_analyst.status_code == 200

    # Viewer: Denied (403 Forbidden)
    res_viewer = client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_viewer.status_code == 403

    # Unauthenticated: Denied (401 Unauthorized)
    res_unauth = client.post("/api/v1/simulation/run", json=payload)
    assert res_unauth.status_code == 401


def test_simulation_latest_metadata_endpoint():
    """Verify that GET /api/v1/simulation/latest accurately reflects recent simulation run."""
    payload = {
        "location_ids": [loc1_id, loc2_id],
        "duration_hours": 3,
        "interval_minutes": 60,
        "scenario": "POLLUTION_SPIKE",
        "seed": 88,
    }
    client.post(
        "/api/v1/simulation/run",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Viewer can access GET /latest metadata
    res = client.get(
        "/api/v1/simulation/latest",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data is not None
    assert data["scenario"] == "POLLUTION_SPIKE"
    assert data["location_count"] == 2
    assert data["readings_generated"] == 8  # 4 steps * 2 locs
    assert data["seed"] == 88
