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
from backend.app.models.aqi import AQIRecord
from backend.app.models.alert import Alert, AlertRule, AlertSeverity, AlertStatus, AlertType
from backend.app.services.aqi_engine import calculate_aqi

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
loc_id = 0
loc_missing_id = 0
loc_sim_id = 0


@pytest.fixture(autouse=True)
def setup_what_if_test_db():
    global admin_token, analyst_token, viewer_token
    global loc_id, loc_missing_id, loc_sim_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Create users
    admin = User(
        username="admin_wi",
        email="admin_wi@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_wi",
        email="analyst_wi@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_wi",
        email="viewer_wi@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Login tokens
    r_admin = client.post("/api/v1/auth/login", json={"username": "admin_wi", "password": "AdminPass123!"})
    admin_token = r_admin.json()["access_token"]

    r_analyst = client.post("/api/v1/auth/login", json={"username": "analyst_wi", "password": "AnalystPass123!"})
    analyst_token = r_analyst.json()["access_token"]

    r_viewer = client.post("/api/v1/auth/login", json={"username": "viewer_wi", "password": "ViewerPass123!"})
    viewer_token = r_viewer.json()["access_token"]

    # Data sources
    ds_api = DataSource(name="CPCB API Source", source_type=SourceType.API)
    ds_sim = DataSource(name="Simulation Engine", source_type=SourceType.SIMULATED)
    db.add_all([ds_api, ds_sim])
    db.commit()

    # Location 1: Standard comprehensive station (Delhi Anand Vihar)
    loc1 = Location(
        name="Anand Vihar Monitoring Station",
        city="Delhi",
        state="Delhi",
        latitude=28.6469,
        longitude=77.3160,
    )
    # Location 2: Station with missing pollutants (e.g. missing PM2.5 or insufficient data)
    loc2 = Location(
        name="Sparse Sensor Station",
        city="Bengaluru",
        state="Karnataka",
        latitude=12.9716,
        longitude=77.5946,
    )
    # Location 3: Station with simulated source
    loc3 = Location(
        name="Synthetic Simulation Station",
        city="Mumbai",
        state="Maharashtra",
        latitude=19.0760,
        longitude=72.8777,
    )
    db.add_all([loc1, loc2, loc3])
    db.commit()

    loc_id = loc1.id
    loc_missing_id = loc2.id
    loc_sim_id = loc3.id

    now = datetime.now(timezone.utc)

    # Reading for Location 1: Moderate baseline (PM2.5: 80, PM10: 150, NO2: 60, SO2: 30, CO: 1.5, O3: 40)
    # CPCB Sub-indices: PM2.5: 80 -> ~167 (Moderate), PM10: 150 -> 133 (Moderate), NO2: 60 -> 75 (Satisfactory)
    # Overall AQI = 167 (Moderate), dominant = PM2.5
    reading1 = AirQualityReading(
        location_id=loc_id,
        timestamp=now - timedelta(minutes=10),
        pm25=80.0,
        pm10=150.0,
        no2=60.0,
        so2=30.0,
        co=1.5,
        o3=40.0,
        source_id=ds_api.id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading1)
    db.commit()

    # Cache AQIRecord
    res1 = calculate_aqi(pm25=80.0, pm10=150.0, no2=60.0, so2=30.0, co=1.5, o3=40.0)
    aqi_rec1 = AQIRecord(
        location_id=loc_id,
        reading_id=reading1.id,
        timestamp=reading1.timestamp,
        aqi=res1.aqi,
        category=res1.category,
        dominant_pollutant=res1.dominant_pollutant,
        pollutant_subindices=res1.pollutant_subindices,
        calculation_method=res1.calculation_method,
        status=res1.status.value,
    )
    db.add(aqi_rec1)

    # Reading for Location 2: Sparse data (missing PM2.5 and PM10, only NO2 & SO2 -> insufficient data)
    reading2 = AirQualityReading(
        location_id=loc_missing_id,
        timestamp=now - timedelta(minutes=10),
        pm25=None,  # Missing PM2.5
        pm10=None,  # Missing PM10
        no2=45.0,
        so2=20.0,
        co=None,
        o3=None,
        source_id=ds_api.id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading2)

    # Reading for Location 3: Simulated source
    reading3 = AirQualityReading(
        location_id=loc_sim_id,
        timestamp=now - timedelta(minutes=10),
        pm25=45.0,
        pm10=80.0,
        no2=30.0,
        so2=15.0,
        co=0.8,
        o3=25.0,
        source_id=ds_sim.id,
        source_type=SourceType.SIMULATED,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading3)

    # Active Alert Rules in DB
    rule_poor = AlertRule(
        name="Poor AQI Exceedance",
        alert_type=AlertType.AQI_THRESHOLD,
        threshold=201.0,
        severity=AlertSeverity.HIGH,
        enabled=True,
    )
    rule_severe = AlertRule(
        name="Severe AQI Alert",
        alert_type=AlertType.AQI_THRESHOLD,
        threshold=401.0,
        severity=AlertSeverity.CRITICAL,
        enabled=True,
    )
    db.add_all([rule_poor, rule_severe])
    db.commit()
    db.close()


# 1. PM2.5 +20%
def test_what_if_pm25_increase_20pct():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 20.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["baseline"]["aqi"] in [166, 167]
    assert data["baseline"]["category"] == "Moderate"
    assert data["scenario"]["modified_pollutant_values"]["pm25"] == pytest.approx(96.0, rel=1e-2)
    # PM2.5 = 96 µg/m³ -> CPCB subindex ~ 220 (Poor category)
    assert data["scenario"]["simulated_aqi"] > data["baseline"]["aqi"]
    assert data["scenario"]["category"] in ["Poor", "Moderate"]
    assert data["impact"]["direction"] == "WORSENED"
    assert data["impact"]["aqi_delta"] > 0
    assert data["scenario_provenance"] == "WHAT_IF / SIMULATED"


# 2. PM2.5 -20%
def test_what_if_pm25_decrease_20pct():
    headers = {"Authorization": f"Bearer {viewer_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": -20.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario"]["modified_pollutant_values"]["pm25"] == pytest.approx(64.0, rel=1e-2)
    assert data["scenario"]["simulated_aqi"] <= data["baseline"]["aqi"]
    assert data["impact"]["direction"] == "IMPROVED"
    assert data["impact"]["aqi_delta"] < 0


# 3. PM10 change
def test_what_if_pm10_change():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm10": 50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["pm10"] == pytest.approx(225.0, rel=1e-2)


# 4. NO2 change
def test_what_if_no2_change():
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"no2": 30.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["no2"] == pytest.approx(78.0, rel=1e-2)


# 5. SO2 change
def test_what_if_so2_change():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"so2": -50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["so2"] == pytest.approx(15.0, rel=1e-2)


# 6. O3 change
def test_what_if_o3_change():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"o3": 100.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["o3"] == pytest.approx(80.0, rel=1e-2)


# 7. CO change
def test_what_if_co_change():
    headers = {"Authorization": f"Bearer {viewer_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"co": 40.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["co"] == pytest.approx(2.1, rel=1e-2)


# 8. NH3 change (pollutant not present in baseline observation -> reject or NULL safety)
def test_what_if_nh3_change():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"nh3": 20.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    # NH3 is None in baseline reading, so should return 400 Bad Request with explanatory message
    assert resp.status_code == 400
    assert "NH3 is unavailable for the selected observation" in resp.json()["detail"]


# 9. Pb change (pollutant not present in baseline observation -> reject or NULL safety)
def test_what_if_pb_change():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pb": 10.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 400
    assert "Pb is unavailable for the selected observation" in resp.json()["detail"]


# 10. Multiple pollutant changes simultaneously
def test_what_if_multiple_pollutants():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {
            "pm25": 20.0,
            "pm10": 10.0,
            "no2": -15.0,
        },
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["pm25"] == pytest.approx(96.0, rel=1e-2)
    assert data["scenario"]["modified_pollutant_values"]["pm10"] == pytest.approx(165.0, rel=1e-2)
    assert data["scenario"]["modified_pollutant_values"]["no2"] == pytest.approx(51.0, rel=1e-2)


# 11. Zero change scenario
def test_what_if_zero_change():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 0.0, "pm10": 0.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["impact"]["aqi_delta"] == 0
    assert data["impact"]["direction"] == "UNCHANGED"
    assert data["scenario"]["simulated_aqi"] == data["baseline"]["aqi"]


# 12. -100% boundary
def test_what_if_negative_100_boundary():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": -100.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["scenario"]["modified_pollutant_values"]["pm25"] == 0.0


# 13. Invalid percentage (< -100% or > 500%)
def test_what_if_invalid_percentage():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # Below -100%
    resp = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_id, "pollutant_changes": {"pm25": -120.0}},
        headers=headers,
    )
    assert resp.status_code == 422 or resp.status_code == 400

    # Above 500%
    resp2 = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_id, "pollutant_changes": {"pm25": 600.0}},
        headers=headers,
    )
    assert resp2.status_code == 422 or resp2.status_code == 400


# 14. Negative concentration prevention
def test_what_if_negative_concentration_prevention():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    resp = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_id, "pollutant_changes": {"pm25": -150.0}},
        headers=headers,
    )
    assert resp.status_code in [400, 422]


# 15. NULL pollutant safety
def test_what_if_null_pollutant_safety():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # Station 2 has PM2.5 as NULL
    resp = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_missing_id, "pollutant_changes": {"pm25": 20.0}},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "PM2.5 is unavailable for the selected observation" in resp.json()["detail"]


# 16. Insufficient AQI data in baseline
def test_what_if_insufficient_aqi_data():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # Station 2 only has NO2 and SO2 (no PM2.5 or PM10)
    resp = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_missing_id, "pollutant_changes": {"no2": 10.0}},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "insufficient" in resp.json()["detail"].lower()


# 17. AQI recalculation through existing CPCB engine
def test_what_if_cpcb_engine_reuse():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Calculate expected AQI directly from calculate_aqi with modified PM2.5 = 120.0
    expected = calculate_aqi(pm25=120.0, pm10=150.0, no2=60.0, so2=30.0, co=1.5, o3=40.0)
    assert data["scenario"]["simulated_aqi"] == expected.aqi
    assert data["scenario"]["category"] == expected.category
    assert data["scenario"]["dominant_pollutant"] == expected.dominant_pollutant


# 18. Category transition: Moderate to Poor
def test_what_if_category_transition():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # PM2.5 80 -> +50% = 120 (AQI ~290 or Poor)
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["impact"]["category_before"] == "Moderate"
    assert data["impact"]["category_after"] == "Poor"
    assert "Moderate → Poor" in data["impact"]["category_transition"]
    assert data["impact"]["direction"] == "WORSENED"


# 19. Category improvement: Moderate to Satisfactory
def test_what_if_category_improvement():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # PM2.5: -50% (40), PM10: -50% (75) -> AQI ~75 (Satisfactory)
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": -50.0, "pm10": -50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["impact"]["category_before"] == "Moderate"
    assert data["impact"]["category_after"] == "Satisfactory"
    assert "Moderate → Satisfactory" in data["impact"]["category_transition"]
    assert data["impact"]["direction"] == "IMPROVED"


# 20. Dominant pollutant transition
def test_what_if_dominant_pollutant_transition():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # PM2.5 -50% (40 -> sub ~67), PM10 +80% (270 -> sub ~220) -> PM10 becomes dominant!
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": -50.0, "pm10": 80.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["impact"]["dominant_pollutant_before"] == "PM2.5"
    assert data["impact"]["dominant_pollutant_after"] == "PM10"
    assert "Changed from PM2.5 to PM10" in data["impact"]["dominant_pollutant_transition"]


# 21. Dominant pollutant unchanged
def test_what_if_dominant_pollutant_unchanged():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 10.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["impact"]["dominant_pollutant_before"] == data["impact"]["dominant_pollutant_after"]
    assert "remains" in data["impact"]["dominant_pollutant_transition"].lower()


# 22. AQI delta calculation
def test_what_if_aqi_delta_calculation():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 20.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    expected_delta = data["scenario"]["simulated_aqi"] - data["baseline"]["aqi"]
    assert data["impact"]["aqi_delta"] == expected_delta
    expected_pct = (expected_delta / data["baseline"]["aqi"]) * 100.0
    assert data["impact"]["aqi_percent_delta"] == pytest.approx(expected_pct, rel=1e-2)


# 23. Provenance tracking
def test_what_if_provenance():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # Location 1: API baseline
    resp1 = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_id, "pollutant_changes": {"pm25": 10.0}},
        headers=headers,
    )
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["baseline_provenance"] == "API"
    assert d1["scenario_provenance"] == "WHAT_IF / SIMULATED"

    # Location 3: SIMULATED baseline
    resp2 = client.post(
        "/api/v1/what-if/simulate",
        json={"location_id": loc_sim_id, "pollutant_changes": {"pm25": 10.0}},
        headers=headers,
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["baseline_provenance"] == "SIMULATED"
    assert d2["scenario_provenance"] == "WHAT_IF / SIMULATED"


# 24. Scenario recommendation integration (Phase 11 reuse)
def test_what_if_scenario_recommendation_integration():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # Push to Poor category
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    recs = data["recommendations"]
    assert len(recs) > 0
    # In Poor category, there should be MASK_GUIDANCE recommending N95
    types = [r["type"] for r in recs]
    assert "MASK_GUIDANCE" in types
    # Ensure source_type is WHAT_IF / SIMULATED
    assert all(r["source_type"] == "WHAT_IF / SIMULATED" for r in recs)


# 25. Forecast separation
def test_what_if_forecast_separation():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 10.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    # Ensure what-if response does not conflate forecasts into hypothetical scenario
    assert data["scenario_provenance"] == "WHAT_IF / SIMULATED"


# 26. Simulated threshold crossing
def test_what_if_simulated_threshold_crossing():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    # Baseline AQI = 167 (below 201 threshold)
    # Increase PM2.5 by 50% -> AQI ~290 (crosses 201 threshold)
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 50.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    threshold_impact = data["impact"]["threshold_impact"]
    assert threshold_impact is not None
    assert threshold_impact["crosses_threshold"] is True
    assert "crosses" in threshold_impact["message"].lower()


# 27. No actual alert created in database
def test_what_if_no_actual_alert_created():
    db = TestingSessionLocal()
    initial_alert_count = db.query(Alert).count()
    db.close()

    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 100.0},  # Massive increase
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200

    db = TestingSessionLocal()
    final_alert_count = db.query(Alert).count()
    db.close()

    # Zero new rows in Alert table
    assert final_alert_count == initial_alert_count


# 28. RBAC: Admin, Analyst, Viewer allowed, Unauthenticated rejected with 401
def test_what_if_rbac():
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 10.0},
    }
    # 1. Admin
    r_admin = client.post("/api/v1/what-if/simulate", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
    assert r_admin.status_code == 200

    # 2. Analyst
    r_analyst = client.post("/api/v1/what-if/simulate", json=payload, headers={"Authorization": f"Bearer {analyst_token}"})
    assert r_analyst.status_code == 200

    # 3. Viewer
    r_viewer = client.post("/api/v1/what-if/simulate", json=payload, headers={"Authorization": f"Bearer {viewer_token}"})
    assert r_viewer.status_code == 200

    # 4. Unauthenticated
    r_unauth = client.post("/api/v1/what-if/simulate", json=payload)
    assert r_unauth.status_code == 401


# 29. Deterministic repeated execution
def test_what_if_deterministic_execution():
    headers = {"Authorization": f"Bearer {analyst_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 25.0, "pm10": -15.0},
    }
    resp1 = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    resp2 = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)

    d1 = resp1.json()
    d2 = resp2.json()

    assert d1["scenario"]["simulated_aqi"] == d2["scenario"]["simulated_aqi"]
    assert d1["scenario"]["category"] == d2["scenario"]["category"]
    assert d1["impact"]["aqi_delta"] == d2["impact"]["aqi_delta"]
    assert len(d1["recommendations"]) == len(d2["recommendations"])


# 30. Baseline observation remains unchanged in database
def test_what_if_baseline_observation_unchanged():
    db = TestingSessionLocal()
    reading_before = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc_id).first()
    pm25_before = reading_before.pm25
    pm10_before = reading_before.pm10
    db.close()

    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {
        "location_id": loc_id,
        "pollutant_changes": {"pm25": 50.0, "pm10": -30.0},
    }
    resp = client.post("/api/v1/what-if/simulate", json=payload, headers=headers)
    assert resp.status_code == 200

    db = TestingSessionLocal()
    reading_after = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc_id).first()
    assert reading_after.pm25 == pm25_before
    assert reading_after.pm10 == pm10_before
    db.close()
