from datetime import datetime, timedelta, timezone
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
from backend.app.services.aqi_breakpoints import (
    get_aqi_category,
    calculate_sub_index,
    CPCB_BREAKPOINTS,
    AQICategory,
)
from backend.app.services.aqi_engine import (
    calculate_aqi,
    AQIStatus,
    AQICalculationResult,
)
from backend.app.models.aqi import AQIRecord

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
def setup_phase4_db():
    global admin_token, analyst_token, viewer_token, test_loc_id, test_source_id
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Create test users
    admin = User(
        username="admin_p4",
        email="admin_p4@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_p4",
        email="analyst_p4@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_p4",
        email="viewer_p4@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Create baseline Location and DataSource
    loc = Location(
        name="Bengaluru Central Station",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
        description="Core station for AQI testing",
        is_active=True,
    )
    db.add(loc)

    ds = DataSource(
        name="CPCB Baseline",
        source_type=SourceType.API,
        provider="CPCB India",
        is_active=True,
    )
    db.add(ds)
    db.commit()

    test_loc_id = loc.id
    test_source_id = ds.id
    db.close()

    # Login tokens
    admin_token = client.post("/api/v1/auth/login", json={"username": "admin_p4", "password": "AdminPass123!"}).json()["access_token"]
    analyst_token = client.post("/api/v1/auth/login", json={"username": "analyst_p4", "password": "AnalystPass123!"}).json()["access_token"]
    viewer_token = client.post("/api/v1/auth/login", json={"username": "viewer_p4", "password": "ViewerPass123!"}).json()["access_token"]

    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.pop(get_db, None)


# -------------------------------------------------------------
# UNIT TESTS: Breakpoints & Sub-Index Calculations
# -------------------------------------------------------------

def test_pm25_breakpoint_calculation():
    """PM2.5 = 45.0 ug/m3 falls in [31, 60] -> [51, 100]. Expected: 75."""
    sub_index, warning = calculate_sub_index("pm25", 45.0)
    assert sub_index == 75
    assert warning is None


def test_pm10_breakpoint_calculation():
    """PM10 = 150.0 ug/m3 falls in [101, 250] -> [101, 200]. Expected: 134."""
    sub_index, warning = calculate_sub_index("pm10", 150.0)
    assert sub_index == 134
    assert warning is None


def test_no2_breakpoint_calculation():
    """NO2 = 20.0 ug/m3 falls in [0, 40] -> [0, 50]. Expected: 25."""
    sub_index, warning = calculate_sub_index("no2", 20.0)
    assert sub_index == 25
    assert warning is None


def test_so2_breakpoint_calculation():
    """SO2 = 30.0 ug/m3 falls in [0, 40] -> [0, 50]. Expected: 38."""
    sub_index, warning = calculate_sub_index("so2", 30.0)
    assert sub_index == 38
    assert warning is None


def test_co_breakpoint_calculation():
    """CO = 1.5 mg/m3 falls in [1.1, 2.0] -> [51, 100]. Expected: 73."""
    sub_index, warning = calculate_sub_index("co", 1.5)
    assert sub_index == 73
    assert warning is None


def test_o3_breakpoint_calculation():
    """O3 = 75.0 ug/m3 falls in [51, 100] -> [51, 100]. Expected: 75."""
    sub_index, warning = calculate_sub_index("o3", 75.0)
    assert sub_index == 75
    assert warning is None


def test_breakpoint_interpolation_exact_bounds():
    """Boundary test: 0 ug/m3 -> 0, exact breakpoint edges."""
    idx_zero, _ = calculate_sub_index("pm25", 0.0)
    assert idx_zero == 0

    idx_edge, _ = calculate_sub_index("pm25", 30.0)
    assert idx_edge == 50

    idx_next_edge, _ = calculate_sub_index("pm25", 60.0)
    assert idx_next_edge == 100


def test_category_mapping():
    """Verify CPCB NAQI standard category mapping."""
    assert get_aqi_category(25) == "Good"
    assert get_aqi_category(50) == "Good"
    assert get_aqi_category(51) == "Satisfactory"
    assert get_aqi_category(100) == "Satisfactory"
    assert get_aqi_category(101) == "Moderate"
    assert get_aqi_category(200) == "Moderate"
    assert get_aqi_category(201) == "Poor"
    assert get_aqi_category(300) == "Poor"
    assert get_aqi_category(301) == "Very Poor"
    assert get_aqi_category(400) == "Very Poor"
    assert get_aqi_category(401) == "Severe"
    assert get_aqi_category(500) == "Severe"
    assert get_aqi_category(650) == "Severe"


# -------------------------------------------------------------
# ENGINE TESTS: Multi-pollutant, Dominant, Sufficiency, Capping
# -------------------------------------------------------------

def test_overall_aqi_and_dominant_pollutant():
    """
    PM2.5: 45 (Ip=75)
    PM10: 150 (Ip=134)
    NO2: 20 (Ip=25)
    Overall AQI should be max(75, 134, 25) = 134, Dominant: PM10, Category: Moderate.
    """
    result = calculate_aqi(pm25=45.0, pm10=150.0, no2=20.0)
    assert result.status == AQIStatus.CALCULATED
    assert result.aqi == 134
    assert result.dominant_pollutant == "PM10"
    assert result.category == "Moderate"
    assert result.pollutant_subindices["pm25"] == 75
    assert result.pollutant_subindices["pm10"] == 134
    assert result.pollutant_subindices["no2"] == 25


def test_multiple_pollutants_tie_breaker():
    """Dominant pollutant handles ties deterministically."""
    # Both producing subindex = 50
    result = calculate_aqi(pm25=30.0, pm10=50.0, no2=40.0)
    assert result.status == AQIStatus.CALCULATED
    assert result.aqi == 50
    assert result.dominant_pollutant in ["PM2.5", "PM10", "NO2"]


def test_missing_pollutants_remain_null_not_zero():
    """Missing pollutants are NOT treated as 0 and have no sub-index."""
    result = calculate_aqi(pm25=45.0, pm10=150.0, no2=20.0, co=None, so2=None, o3=None)
    assert result.status == AQIStatus.CALCULATED
    assert "co" not in result.pollutant_subindices or result.pollutant_subindices["co"] is None
    assert "so2" not in result.pollutant_subindices or result.pollutant_subindices["so2"] is None
    assert "co" in result.pollutants_unavailable
    assert "so2" in result.pollutants_unavailable


def test_insufficient_data_less_than_three_pollutants():
    """CPCB rule: minimum 3 pollutants required. 2 pollutants -> INSUFFICIENT_DATA."""
    result = calculate_aqi(pm25=45.0, pm10=150.0)
    assert result.status == AQIStatus.INSUFFICIENT_DATA
    assert result.aqi is None
    assert result.category is None
    assert result.dominant_pollutant is None
    assert "At least 3 pollutants are required" in result.message


def test_insufficient_data_missing_particulate():
    """CPCB rule: at least one particulate (PM2.5 or PM10) required. 3 gases only -> INSUFFICIENT_DATA."""
    result = calculate_aqi(pm25=None, pm10=None, no2=40.0, so2=30.0, co=1.0)
    assert result.status == AQIStatus.INSUFFICIENT_DATA
    assert result.aqi is None
    assert "At least one particulate pollutant (PM2.5 or PM10) must be monitored" in result.message


def test_invalid_negative_pollutant():
    """Negative concentrations trigger INVALID_DATA status."""
    result = calculate_aqi(pm25=-10.0, pm10=50.0, no2=40.0)
    assert result.status == AQIStatus.INVALID_DATA
    assert result.aqi is None
    assert "Negative concentration" in result.message


def test_values_above_supported_breakpoints_capped():
    """Concentrations exceeding maximum breakpoint cap sub-index at 500 with warning."""
    # PM2.5 > 380 ug/m3 -> capped at 500
    sub_idx, warning = calculate_sub_index("pm25", 500.0)
    assert sub_idx == 500
    assert warning is not None
    assert "exceeds maximum CPCB breakpoint" in warning

    result = calculate_aqi(pm25=500.0, pm10=100.0, no2=50.0)
    assert result.status == AQIStatus.CALCULATED
    assert result.aqi == 500
    assert result.category == "Severe"
    assert result.dominant_pollutant == "PM2.5"
    assert len(result.warnings) > 0


# -------------------------------------------------------------
# API INTEGRATION TESTS
# -------------------------------------------------------------

def test_api_aqi_endpoint_calculation_and_caching():
    """
    Ingest a reading with PM2.5, PM10, NO2, CO.
    GET /api/v1/aqi/{location_id} should calculate, persist AQIRecord, and return it.
    Calling it again should return the cached record.
    """
    now = datetime.now(timezone.utc)
    res_reading = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 45.0,
            "pm10": 150.0,
            "no2": 20.0,
            "co": 1.5,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert res_reading.status_code == 201

    # First call: Calculates & stores
    res_aqi1 = client.get(
        f"/api/v1/aqi/{test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_aqi1.status_code == 200
    data1 = res_aqi1.json()
    assert data1["location_id"] == test_loc_id
    assert data1["aqi"] == 134
    assert data1["dominant_pollutant"] == "PM10"
    assert data1["category"] == "Moderate"
    assert data1["calculation_method"] == "CPCB_INDIA_V1"
    assert data1["status"] == "CALCULATED"

    # Second call: Retrieves cached record
    res_aqi2 = client.get(
        f"/api/v1/aqi/{test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_aqi2.status_code == 200
    data2 = res_aqi2.json()
    assert data2["id"] == data1["id"]
    assert data2["aqi"] == data1["aqi"]


def test_api_aqi_insufficient_data():
    """Station with only 1 pollutant returns INSUFFICIENT_DATA status."""
    now = datetime.now(timezone.utc)
    # Create distinct location
    loc = client.post(
        "/api/v1/locations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Rural Sensor", "city": "Mysuru", "state": "Karnataka", "latitude": 12.3, "longitude": 76.6},
    ).json()

    client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": loc["id"],
            "timestamp": now.isoformat(),
            "pm25": 45.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )

    res = client.get(
        f"/api/v1/aqi/{loc['id']}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "INSUFFICIENT_DATA"
    assert data["aqi"] is None


def test_api_aqi_history():
    """Historical AQI endpoint returns time-series records."""
    base_time = datetime(2026, 9, 18, 6, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        t = base_time + timedelta(hours=i)
        client.post(
            "/api/v1/air-quality/readings",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={
                "location_id": test_loc_id,
                "timestamp": t.isoformat(),
                "pm25": float(30 + i * 15),
                "pm10": float(60 + i * 20),
                "no2": 25.0,
                "source_id": test_source_id,
                "source_type": "API",
            },
        )

    res = client.get(
        f"/api/v1/aqi/{test_loc_id}/history?limit=2",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    assert all("aqi" in item for item in items)


def test_api_aqi_unauthorized():
    """Unauthenticated requests are rejected."""
    res = client.get(f"/api/v1/aqi/{test_loc_id}")
    assert res.status_code == 401
