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
from backend.app.models.air_quality import AirQualityReading
from backend.app.models.aqi import AQIRecord
from backend.app.services.analytics import (
    calculate_summary_statistics,
    compute_trend_direction,
    aggregate_time_series,
    detect_anomalies,
    detect_pollution_events,
    TrendDirection,
)

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
test_loc2_id = 0
test_source_id = 0


@pytest.fixture(autouse=True)
def setup_phase5_db():
    global admin_token, analyst_token, viewer_token, test_loc_id, test_loc2_id, test_source_id
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Create test users
    admin = User(
        username="admin_p5",
        email="admin_p5@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_p5",
        email="analyst_p5@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_p5",
        email="viewer_p5@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Create baseline Locations
    loc1 = Location(
        name="Bengaluru Central Station",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
        description="Primary analytics testing station",
        is_active=True,
    )
    loc2 = Location(
        name="Delhi Anand Vihar",
        city="Delhi",
        state="Delhi",
        country="India",
        latitude=28.65,
        longitude=77.31,
        description="Secondary comparison station",
        is_active=True,
    )
    db.add_all([loc1, loc2])

    ds = DataSource(
        name="CPCB Baseline",
        source_type=SourceType.API,
        provider="CPCB India",
        is_active=True,
    )
    db.add(ds)
    db.commit()

    test_loc_id = loc1.id
    test_loc2_id = loc2.id
    test_source_id = ds.id
    db.close()

    # Login tokens
    admin_token = client.post("/api/v1/auth/login", json={"username": "admin_p5", "password": "AdminPass123!"}).json()["access_token"]
    analyst_token = client.post("/api/v1/auth/login", json={"username": "analyst_p5", "password": "AnalystPass123!"}).json()["access_token"]
    viewer_token = client.post("/api/v1/auth/login", json={"username": "viewer_p5", "password": "ViewerPass123!"}).json()["access_token"]

    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.pop(get_db, None)


# -------------------------------------------------------------
# UNIT TESTS: Statistical Utilities
# -------------------------------------------------------------

def test_summary_statistics_deterministic_sequence():
    """Known sequence: [10, 20, 30, 40, 50] -> mean=30, median=30, min=10, max=50, stddev=15.81."""
    stats = calculate_summary_statistics([10.0, 20.0, 30.0, 40.0, 50.0])
    assert stats["count"] == 5
    assert stats["mean"] == 30.0
    assert stats["minimum"] == 10.0
    assert stats["maximum"] == 50.0
    assert stats["median"] == 30.0
    assert stats["stddev"] == 15.81


def test_summary_statistics_null_exclusion():
    """Missing (None) values must be strictly excluded without becoming 0."""
    stats = calculate_summary_statistics([10.0, None, 20.0, None, 30.0])
    assert stats["count"] == 3
    assert stats["mean"] == 20.0
    assert stats["minimum"] == 10.0
    assert stats["maximum"] == 30.0
    assert stats["median"] == 20.0
    assert stats["stddev"] == 10.0


def test_summary_statistics_empty_or_all_null():
    """Empty or all-None collections return count=0 and None for aggregates."""
    stats = calculate_summary_statistics([None, None])
    assert stats["count"] == 0
    assert stats["mean"] is None
    assert stats["median"] is None


def test_trend_direction_calculations():
    """Verify INCREASING, DECREASING, STABLE, and INSUFFICIENT_DATA."""
    # Increasing
    inc = compute_trend_direction(recent_values=[50.0, 60.0], baseline_values=[20.0, 25.0])
    assert inc == TrendDirection.INCREASING

    # Decreasing
    dec = compute_trend_direction(recent_values=[20.0, 25.0], baseline_values=[50.0, 60.0])
    assert dec == TrendDirection.DECREASING

    # Stable (within 5% threshold)
    stable = compute_trend_direction(recent_values=[100.0, 102.0], baseline_values=[100.0, 101.0])
    assert stable == TrendDirection.STABLE

    # Insufficient
    insuf = compute_trend_direction(recent_values=[100.0], baseline_values=[])
    assert insuf == TrendDirection.INSUFFICIENT_DATA


def test_time_series_aggregation():
    """Verify temporal aggregation grouping."""
    t0 = datetime(2026, 9, 18, 10, 15, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 18, 10, 45, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 18, 11, 10, tzinfo=timezone.utc)

    records = [
        {"timestamp": t0, "value": 40.0},
        {"timestamp": t1, "value": 60.0},
        {"timestamp": t2, "value": 90.0},
    ]

    # Hourly: Expect 2 buckets: 10:00 (avg 50, max 60, count 2), 11:00 (avg 90, max 90, count 1)
    hourly = aggregate_time_series(records, aggregation="hourly")
    assert len(hourly) == 2
    assert hourly[0]["average"] == 50.0
    assert hourly[0]["maximum"] == 60.0
    assert hourly[0]["count"] == 2
    assert hourly[1]["average"] == 90.0


def test_anomaly_detection_zscore():
    """Z-score anomaly detector flags extreme outlier."""
    normal_values = [50.0, 51.0, 49.0, 52.0, 50.0, 48.0, 51.0, 50.0, 49.0, 50.0]
    base_t = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
    records = [
        {"timestamp": base_t + timedelta(hours=i), "value": v, "location_id": test_loc_id}
        for i, v in enumerate(normal_values)
    ]
    # Inject outlier
    records.append({"timestamp": base_t + timedelta(hours=10), "value": 250.0, "location_id": test_loc_id})

    anomalies = detect_anomalies(records, metric="pm25", method="zscore", threshold=2.5)
    assert len(anomalies) == 1
    assert anomalies[0]["observed_value"] == 250.0
    assert anomalies[0]["metric"] == "pm25"
    assert anomalies[0]["score"] > 2.5
    assert anomalies[0]["severity"] in ["MEDIUM", "HIGH"]


def test_pollution_event_detection():
    """Sustained high AQI sequence is bundled into a single PollutionEvent."""
    base_t = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
    # 4 hours of Severe AQI (250, 260, 270, 280), baseline ~ 50
    records = [
        {"timestamp": base_t, "aqi": 50, "dominant_pollutant": "PM2.5", "location_id": test_loc_id},
        {"timestamp": base_t + timedelta(hours=1), "aqi": 250, "dominant_pollutant": "PM2.5", "location_id": test_loc_id},
        {"timestamp": base_t + timedelta(hours=2), "aqi": 260, "dominant_pollutant": "PM2.5", "location_id": test_loc_id},
        {"timestamp": base_t + timedelta(hours=3), "aqi": 270, "dominant_pollutant": "PM2.5", "location_id": test_loc_id},
        {"timestamp": base_t + timedelta(hours=4), "aqi": 280, "dominant_pollutant": "PM2.5", "location_id": test_loc_id},
        {"timestamp": base_t + timedelta(hours=5), "aqi": 70, "dominant_pollutant": "PM2.5", "location_id": test_loc_id},
    ]

    events = detect_pollution_events(records, aqi_threshold=201, min_duration_hours=2)
    assert len(events) == 1
    evt = events[0]
    assert evt["duration_hours"] == 4.0
    assert evt["max_aqi"] == 280
    assert evt["dominant_pollutant"] == "PM2.5"
    assert "Sustained elevated AQI" in evt["detection_reason"]


# -------------------------------------------------------------
# API INTEGRATION TESTS
# -------------------------------------------------------------

def test_api_analytics_summary():
    """Ingest readings & test /api/v1/analytics/summary."""
    base_t = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        t = base_t + timedelta(hours=i)
        client.post(
            "/api/v1/air-quality/readings",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={
                "location_id": test_loc_id,
                "timestamp": t.isoformat(),
                "pm25": float(30 + i * 10),
                "pm10": float(60 + i * 10),
                "no2": 25.0,
                "source_id": test_source_id,
                "source_type": "API",
            },
        )

    res = client.get(
        f"/api/v1/analytics/summary?location_id={test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["location_id"] == test_loc_id
    assert "aqi_statistics" in data
    assert "pollutant_statistics" in data
    assert "pm25" in data["pollutant_statistics"]
    assert data["pollutant_statistics"]["pm25"]["count"] == 5
    assert data["trend_direction"] in ["INCREASING", "DECREASING", "STABLE", "INSUFFICIENT_DATA"]


def test_api_analytics_aqi_trend():
    """GET /api/v1/analytics/aqi-trend returns aggregated time series."""
    res = client.get(
        f"/api/v1/analytics/aqi-trend?location_id={test_loc_id}&aggregation=hourly",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_api_analytics_pollutant_trend():
    """GET /api/v1/analytics/pollutants/{pollutant}."""
    res = client.get(
        f"/api/v1/analytics/pollutants/pm25?location_id={test_loc_id}&aggregation=hourly",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_api_analytics_location_comparison():
    """GET /api/v1/analytics/location-comparison compares stations."""
    # Post reading for second location
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc).isoformat()
    client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc2_id,
            "timestamp": now,
            "pm25": 90.0,
            "pm10": 180.0,
            "no2": 50.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )

    res = client.get(
        "/api/v1/analytics/location-comparison",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 2
    assert all("average_aqi" in item for item in items)
    assert all("dominant_pollutant" in item for item in items)


def test_api_analytics_anomalies_and_events():
    """GET /api/v1/analytics/anomalies and /events."""
    res_anom = client.get(
        f"/api/v1/analytics/anomalies?location_id={test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_anom.status_code == 200
    assert isinstance(res_anom.json(), list)

    res_events = client.get(
        f"/api/v1/analytics/events?location_id={test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_events.status_code == 200
    assert isinstance(res_events.json(), list)


def test_api_analytics_hotspots():
    """GET /api/v1/analytics/hotspots returns objective metrics without subjective labels."""
    res = client.get(
        "/api/v1/analytics/hotspots",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)
    for item in items:
        assert "mean_aqi" in item
        assert "max_aqi" in item
        assert "high_pollution_hours" in item
        # Ensure NO subjective labels like 'worst' or 'most dangerous'
        assert "worst" not in item
        assert "danger" not in item


def test_api_analytics_validation_invalid_dates():
    """start_time > end_time returns 422 Unprocessable Entity."""
    t_start = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc).isoformat()
    t_end = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc).isoformat()

    res = client.get(
        "/api/v1/analytics/summary",
        params={
            "location_id": test_loc_id,
            "start_time": t_start,
            "end_time": t_end,
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 422
    assert "start_time must be earlier than end_time" in res.json()["detail"]


def test_api_analytics_validation_invalid_pollutant():
    """Invalid pollutant returns 422."""
    res = client.get(
        f"/api/v1/analytics/pollutants/unobtanium?location_id={test_loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 422


def test_api_analytics_validation_invalid_aggregation():
    """Invalid aggregation returns 422."""
    res = client.get(
        f"/api/v1/analytics/aqi-trend?location_id={test_loc_id}&aggregation=secondly",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 422


def test_api_analytics_unauthorized():
    """Unauthenticated requests are rejected with 401."""
    res = client.get(f"/api/v1/analytics/summary?location_id={test_loc_id}")
    assert res.status_code == 401
