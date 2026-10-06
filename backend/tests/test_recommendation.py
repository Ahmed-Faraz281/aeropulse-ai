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
from backend.app.models.prediction import PredictionRecord
from backend.app.models.alert import Alert, AlertRule, AlertSeverity, AlertStatus, AlertType
from backend.app.services.recommendation_service import (
    evaluate_location_recommendations,
    RecommendationType,
    RecommendationPriority,
)

# In-memory test SQLite DB
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
loc_sim_id = 0


@pytest.fixture(autouse=True)
def setup_recommendations_test_db():
    global admin_token, analyst_token, viewer_token
    global loc_id, loc_sim_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Users
    admin = User(
        username="admin_rec",
        email="admin_rec@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_rec",
        email="analyst_rec@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_rec",
        email="viewer_rec@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Locations
    loc1 = Location(
        name="Central Park Station",
        city="Delhi",
        state="Delhi",
        country="India",
        latitude=28.6139,
        longitude=77.2090,
    )
    loc2 = Location(
        name="Synthetic Testing Hub",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
    )
    db.add_all([loc1, loc2])
    db.commit()
    db.refresh(loc1)
    db.refresh(loc2)
    loc_id = loc1.id
    loc_sim_id = loc2.id

    # Data sources
    ds_api = DataSource(
        name="CPCB Public API",
        source_type=SourceType.API,
        is_active=True,
    )
    ds_sim = DataSource(
        name="Synthetic Telemetry Simulator",
        source_type=SourceType.SIMULATED,
        is_active=True,
    )
    db.add_all([ds_api, ds_sim])
    db.commit()
    db.close()

    # Obtain JWT tokens
    res_adm = client.post(
        "/api/v1/auth/login",
        data={"username": "admin_rec", "password": "AdminPass123!"},
    )
    admin_token = res_adm.json()["access_token"]

    res_anl = client.post(
        "/api/v1/auth/login",
        data={"username": "analyst_rec", "password": "AnalystPass123!"},
    )
    analyst_token = res_anl.json()["access_token"]

    res_viw = client.post(
        "/api/v1/auth/login",
        data={"username": "viewer_rec", "password": "ViewerPass123!"},
    )
    viewer_token = res_viw.json()["access_token"]


def _seed_telemetry(
    db,
    location_id: int,
    aqi: int,
    category: str,
    dominant: str = "pm25",
    pm25: float = 30.0,
    pm10: float = 60.0,
    no2: float = 20.0,
    so2: float = 10.0,
    co: float = 0.5,
    o3: float = 25.0,
    source_type: SourceType = SourceType.API,
    trend_readings: int = 5,
    trend_slope: float = 0.0,
):
    """Helper to seed historical and current readings with associated AQIRecord."""
    ds = db.query(DataSource).filter(DataSource.source_type == source_type).first()
    now = datetime.now(timezone.utc)

    # Seed baseline/prior readings
    for i in range(trend_readings, 0, -1):
        t = now - timedelta(hours=i)
        prior_aqi = max(10, int(aqi - (i * trend_slope)))
        r = AirQualityReading(
            location_id=location_id,
            source_id=ds.id,
            source_type=ds.source_type,
            timestamp=t,
            pm25=pm25,
            pm10=pm10,
            no2=no2,
            quality_status=QualityStatus.VALID,
        )
        db.add(r)
        db.flush()
        aq_rec = AQIRecord(
            reading_id=r.id,
            location_id=location_id,
            timestamp=t,
            aqi=prior_aqi,
            category=category,
            dominant_pollutant=dominant,
            calculation_method="CPCB_INDIA_V1",
        )
        db.add(aq_rec)

    # Seed current reading
    curr_r = AirQualityReading(
        location_id=location_id,
        source_id=ds.id,
        source_type=ds.source_type,
        timestamp=now,
        pm25=pm25,
        pm10=pm10,
        no2=no2,
        so2=so2,
        co=co,
        o3=o3,
        quality_status=QualityStatus.VALID,
    )
    db.add(curr_r)
    db.flush()
    curr_aq = AQIRecord(
        reading_id=curr_r.id,
        location_id=location_id,
        timestamp=now,
        aqi=aqi,
        category=category,
        dominant_pollutant=dominant,
        calculation_method="CPCB_INDIA_V1",
    )
    db.add(curr_aq)
    db.commit()
    return curr_r, curr_aq


def test_recommendation_good_aqi():
    """Good AQI (<=50): normal activity recommendations, lowest priority (INFO)."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=35, category="Good", dominant="pm25", pm25=12.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.current_aqi == 35
    assert res.current_category == "Good"
    assert len(res.recommendations) > 0

    # Ensure outdoor activity is suitable
    outdoor_rec = next((r for r in res.recommendations if r.type == RecommendationType.OUTDOOR_ACTIVITY), None)
    assert outdoor_rec is not None
    assert outdoor_rec.priority == RecommendationPriority.INFO
    assert "suitable" in outdoor_rec.action.lower() or "normal" in outdoor_rec.action.lower()
    assert outdoor_rec.triggered_by == "AQI_CATEGORY"


def test_recommendation_satisfactory_aqi():
    """Satisfactory AQI (51-100): normal activity with caution for sensitive groups."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=75, category="Satisfactory", dominant="pm10", pm10=80.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.current_aqi == 75
    assert res.current_category == "Satisfactory"
    assert any("sensitive" in r.message.lower() or "satisfactory" in r.reason.lower() for r in res.recommendations)


def test_recommendation_moderate_aqi():
    """Moderate AQI (101-200): advice to reduce prolonged strenuous exertion."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=150, category="Moderate", dominant="pm25", pm25=55.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.current_aqi == 150
    assert res.current_category == "Moderate"
    assert any("reduce" in r.action.lower() or "discomfort" in r.reason.lower() for r in res.recommendations)


def test_recommendation_poor_aqi():
    """Poor AQI (201-300): postpone strenuous exercise, wear mask outdoors."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=260, category="Poor", dominant="pm25", pm25=110.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.current_aqi == 260
    assert res.current_category == "Poor"
    mask_rec = next((r for r in res.recommendations if r.type == RecommendationType.MASK_GUIDANCE), None)
    assert mask_rec is not None
    assert mask_rec.priority in [RecommendationPriority.MEDIUM, RecommendationPriority.HIGH]


def test_recommendation_very_poor_aqi():
    """Very Poor AQI (301-400): minimize outdoor exposure, use indoor filtration."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=340, category="Very Poor", dominant="pm25", pm25=180.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.current_aqi == 340
    assert res.current_category == "Very Poor"
    exp_rec = next((r for r in res.recommendations if r.type == RecommendationType.EXPOSURE_REDUCTION), None)
    assert exp_rec is not None
    assert exp_rec.priority == RecommendationPriority.HIGH


def test_recommendation_severe_aqi():
    """Severe AQI (401+): strictly avoid outdoor exposure, remain indoors, CRITICAL priority."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=440, category="Severe", dominant="pm25", pm25=300.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.current_aqi == 440
    assert res.current_category == "Severe"
    critical_recs = [r for r in res.recommendations if r.priority == RecommendationPriority.CRITICAL]
    assert len(critical_recs) > 0
    assert any("avoid" in r.action.lower() for r in critical_recs)


def test_recommendation_pm25_dominant():
    """PM2.5 dominant triggers specific particulate filtration and N95 advice."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=220, category="Poor", dominant="pm25", pm25=95.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    pm25_rec = next((r for r in res.recommendations if r.type == RecommendationType.POLLUTANT_SPECIFIC and "PM2.5" in r.title), None)
    assert pm25_rec is not None
    assert "pm2.5" in pm25_rec.reason.lower()
    assert pm25_rec.triggered_by == "DOMINANT_POLLUTANT"


def test_recommendation_pm10_dominant():
    """PM10 dominant triggers dust control and damp mopping advice."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=210, category="Poor", dominant="pm10", pm10=280.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    pm10_rec = next((r for r in res.recommendations if r.type == RecommendationType.POLLUTANT_SPECIFIC and "PM10" in r.title), None)
    assert pm10_rec is not None
    assert "dust" in pm10_rec.action.lower() or "dust" in pm10_rec.message.lower()


def test_recommendation_o3_dominant():
    """O3 dominant triggers afternoon photochemical peak timing advice."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=160, category="Moderate", dominant="o3", o3=180.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    o3_rec = next((r for r in res.recommendations if r.type == RecommendationType.POLLUTANT_SPECIFIC and "Ozone" in r.title), None)
    assert o3_rec is not None
    assert "afternoon" in o3_rec.action.lower() or "afternoon" in o3_rec.message.lower()


def test_recommendation_no2_dominant():
    """NO2 dominant triggers traffic corridor avoidance and rush-hour timing advice."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=140, category="Moderate", dominant="no2", no2=120.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    no2_rec = next((r for r in res.recommendations if r.type == RecommendationType.POLLUTANT_SPECIFIC and "NO2" in r.title), None)
    assert no2_rec is not None
    assert "traffic" in no2_rec.action.lower() or "traffic" in no2_rec.message.lower()


def test_recommendation_co_dominant():
    """CO dominant triggers indoor ventilation and combustion avoidance guidance."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=130, category="Moderate", dominant="co", co=3.5)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    co_rec = next((r for r in res.recommendations if r.type == RecommendationType.POLLUTANT_SPECIFIC and "CO" in r.title), None)
    assert co_rec is not None
    assert "combustion" in co_rec.message.lower() or "ventilat" in co_rec.action.lower()


def test_recommendation_so2_dominant():
    """SO2 dominant triggers sulfur dioxide exposure reduction advice."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=130, category="Moderate", dominant="so2", so2=110.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    so2_rec = next((r for r in res.recommendations if r.type == RecommendationType.POLLUTANT_SPECIFIC and "SO2" in r.title), None)
    assert so2_rec is not None
    assert "industrial" in so2_rec.message.lower() or "so2" in so2_rec.reason.lower()


def test_recommendation_increasing_trend():
    """Increasing trend triggers worsening condition advice."""
    db = TestingSessionLocal()
    # Trend slope > 0 -> prior readings were lower, so current reading represents an increase
    _seed_telemetry(db, loc_id, aqi=220, category="Poor", trend_slope=15.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.trend in ["INCREASING", "RISING"]
    trend_rec = next((r for r in res.recommendations if r.triggered_by == "TREND"), None)
    assert trend_rec is not None
    assert "worsening" in trend_rec.message.lower() or "increasing" in trend_rec.reason.lower()


def test_recommendation_decreasing_trend():
    """Decreasing trend acknowledges improving conditions while maintaining monitoring."""
    db = TestingSessionLocal()
    # Trend slope < 0 -> prior readings were higher, so current reading represents a decrease
    _seed_telemetry(db, loc_id, aqi=180, category="Moderate", trend_slope=-15.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.trend in ["DECREASING", "FALLING"]
    trend_rec = next((r for r in res.recommendations if r.triggered_by == "TREND"), None)
    assert trend_rec is not None
    assert "improving" in trend_rec.message.lower() or "decreasing" in trend_rec.reason.lower()


def test_recommendation_stable_trend():
    """Stable trend is properly recognized and does not produce redundant trend alarms."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=90, category="Satisfactory", trend_slope=0.0)
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert res.trend == "STABLE"


def test_recommendation_forecast_based():
    """Forecast integration triggers preventive advice clearly labeled as PREDICTED."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=170, category="Moderate")
    now = datetime.now(timezone.utc)

    # Insert PredictionRecord indicating deterioration to 280 (Poor) in 3h
    pred = PredictionRecord(
        location_id=loc_id,
        base_timestamp=now,
        target_timestamp=now + timedelta(hours=3),
        horizon_hours=3,
        predicted_aqi=280.0,
        predicted_category="Poor",
        training_observations=50,
        has_simulated_data=False,
    )
    db.add(pred)
    db.commit()

    res = evaluate_location_recommendations(db, loc_id, include_forecast=True)
    db.close()

    forecast_rec = next((r for r in res.recommendations if r.forecast_based), None)
    assert forecast_rec is not None
    assert forecast_rec.type == RecommendationType.FORECAST_PREVENTION
    assert forecast_rec.source_type == "PREDICTED"
    assert "forecast" in forecast_rec.title.lower() or "forecast" in forecast_rec.message.lower()
    assert "3h" in forecast_rec.reason or "280" in forecast_rec.reason


def test_recommendation_alert_based():
    """Active alerts from Phase 10 trigger direct alert-response recommendations."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=320, category="Very Poor")
    now = datetime.now(timezone.utc)

    rule = AlertRule(
        name="Severe Warning",
        alert_type=AlertType.SUSTAINED_HIGH_AQI,
        threshold=300.0,
        duration_hours=3.0,
        severity=AlertSeverity.HIGH,
        enabled=True,
    )
    db.add(rule)
    db.flush()

    alert = Alert(
        rule_id=rule.id,
        location_id=loc_id,
        alert_type=AlertType.SUSTAINED_HIGH_AQI,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.ACTIVE,
        title="Sustained High AQI Alert",
        message="AQI has exceeded 300 for over 3 hours.",
        observed_value=320.0,
        threshold_value=300.0,
        source_type="API",
        detected_at=now,
    )
    db.add(alert)
    db.commit()

    res = evaluate_location_recommendations(db, loc_id, include_alerts=True)
    db.close()

    alert_rec = next((r for r in res.recommendations if r.type == RecommendationType.ALERT_RESPONSE), None)
    assert alert_rec is not None
    assert alert_rec.priority in [RecommendationPriority.HIGH, RecommendationPriority.CRITICAL]
    assert "alert" in alert_rec.reason.lower()


def test_recommendation_simulated_provenance():
    """Readings from SIMULATED data source preserve SIMULATED provenance throughout."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_sim_id, aqi=215, category="Poor", source_type=SourceType.SIMULATED)
    res = evaluate_location_recommendations(db, loc_sim_id)
    db.close()

    assert res.source_type == "SIMULATED"
    assert res.has_simulated_data is True
    assert all(r.source_type == "SIMULATED" for r in res.recommendations if not r.forecast_based)


def test_recommendation_missing_pollutant_handling():
    """Missing pollutant values strictly remain NULL and do not trigger false rules."""
    db = TestingSessionLocal()
    ds = db.query(DataSource).filter(DataSource.source_type == SourceType.API).first()
    now = datetime.now(timezone.utc)

    # Reading with ONLY pm25, all others NULL
    r = AirQualityReading(
        location_id=loc_id,
        source_id=ds.id,
        source_type=ds.source_type,
        timestamp=now,
        pm25=45.0,
        pm10=None,
        no2=None,
        so2=None,
        co=None,
        o3=None,
        quality_status=QualityStatus.VALID,
    )
    db.add(r)
    db.flush()
    aq = AQIRecord(
        reading_id=r.id,
        location_id=loc_id,
        timestamp=now,
        aqi=45,
        category="Good",
        dominant_pollutant="pm25",
        calculation_method="CPCB_INDIA_V1",
    )
    db.add(aq)
    db.commit()

    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    # Should not produce PM10 or Ozone specific recommendations
    assert not any("PM10" in r.title for r in res.recommendations)
    assert not any("Ozone" in r.title for r in res.recommendations)


def test_recommendation_missing_prediction_handling():
    """When no predictions exist, system operates normally without hallucinated forecast advice."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=80, category="Satisfactory")
    res = evaluate_location_recommendations(db, loc_id, include_forecast=True)
    db.close()

    assert res.forecast_summary is None
    assert not any(r.forecast_based for r in res.recommendations)


def test_recommendation_deduplication():
    """Duplicate/overlapping recommendations for identical conditions are consolidated."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=280, category="Poor")
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    # Ensure no two recommendations have identical action strings
    actions = [r.action.strip().lower() for r in res.recommendations]
    assert len(actions) == len(set(actions))


def test_recommendation_priority_ordering():
    """Recommendations are strictly sorted by priority (CRITICAL > HIGH > MEDIUM > LOW > INFO)."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=360, category="Very Poor")
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    priority_order = {
        RecommendationPriority.CRITICAL: 4,
        RecommendationPriority.HIGH: 3,
        RecommendationPriority.MEDIUM: 2,
        RecommendationPriority.LOW: 1,
        RecommendationPriority.INFO: 0,
    }

    for i in range(len(res.recommendations) - 1):
        p_curr = priority_order[res.recommendations[i].priority]
        p_next = priority_order[res.recommendations[i + 1].priority]
        assert p_curr >= p_next, f"Recommendation {res.recommendations[i].title} ({res.recommendations[i].priority}) ordered after {res.recommendations[i+1].title} ({res.recommendations[i+1].priority})"


def test_recommendation_explainability_fields():
    """Every recommendation has non-empty explainability fields: reason, triggered_by, supporting_data."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=230, category="Poor", dominant="pm25")
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    for r in res.recommendations:
        assert r.reason and len(r.reason) > 5
        assert r.triggered_by and len(r.triggered_by) > 0
        assert isinstance(r.supporting_data, dict)


def test_recommendation_rbac_access():
    """ADMIN, ANALYST, and VIEWER can view recommendations; unauthenticated gets 401."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=95, category="Satisfactory")
    db.close()

    # Unauthenticated
    unauth = client.get(f"/api/v1/recommendations/{loc_id}")
    assert unauth.status_code == 401

    # Viewer
    res_viw = client.get(
        f"/api/v1/recommendations/{loc_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_viw.status_code == 200
    assert "recommendations" in res_viw.json()

    # Analyst
    res_anl = client.get(
        f"/api/v1/recommendations/{loc_id}",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res_anl.status_code == 200

    # Admin
    res_adm = client.get(
        f"/api/v1/recommendations/{loc_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_adm.status_code == 200


def test_recommendation_no_medical_diagnosis():
    """System maintains non-medical positioning, includes disclaimer, and makes no diagnostic claims."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=480, category="Severe")
    res = evaluate_location_recommendations(db, loc_id)
    db.close()

    # Disclaimer is present
    assert res.disclaimer and "not medical advice" in res.disclaimer.lower()

    # No diagnostic / prescription claims
    forbidden_terms = ["prescribe", "diagnose", "cure", "treatment for asthma", "clinical diagnosis", "take medicine"]
    for r in res.recommendations:
        text = f"{r.title} {r.action} {r.message} {r.reason}".lower()
        for term in forbidden_terms:
            assert term not in text, f"Forbidden medical term '{term}' found in recommendation {r.title}"


def test_recommendation_deterministic_output():
    """Identical database state yields identical recommendations and ordering across multiple evaluations."""
    db = TestingSessionLocal()
    _seed_telemetry(db, loc_id, aqi=215, category="Poor", dominant="pm25")

    res1 = evaluate_location_recommendations(db, loc_id)
    res2 = evaluate_location_recommendations(db, loc_id)
    db.close()

    assert len(res1.recommendations) == len(res2.recommendations)
    for r1, r2 in zip(res1.recommendations, res2.recommendations):
        assert r1.id == r2.id
        assert r1.title == r2.title
        assert r1.action == r2.action
        assert r1.priority == r2.priority
        assert r1.reason == r2.reason
