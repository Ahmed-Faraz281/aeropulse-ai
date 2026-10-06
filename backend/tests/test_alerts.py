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
loc_a_id = 0
loc_b_id = 0
loc_sim_id = 0


@pytest.fixture(autouse=True)
def setup_alerts_test_db():
    global admin_token, analyst_token, viewer_token
    global loc_a_id, loc_b_id, loc_sim_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Users
    admin = User(
        username="admin_alt",
        email="admin_alt@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_alt",
        email="analyst_alt@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_alt",
        email="viewer_alt@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Locations
    loc_a = Location(
        name="Station Indiranagar",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9784,
        longitude=77.6408,
        is_active=True,
    )
    loc_b = Location(
        name="Station Whitefield",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9698,
        longitude=77.7500,
        is_active=True,
    )
    loc_sim = Location(
        name="Station Delhi Sim",
        city="Delhi",
        state="Delhi",
        country="India",
        latitude=28.6139,
        longitude=77.2090,
        is_active=True,
    )
    db.add_all([loc_a, loc_b, loc_sim])
    db.commit()
    db.refresh(loc_a)
    db.refresh(loc_b)
    db.refresh(loc_sim)

    loc_a_id = loc_a.id
    loc_b_id = loc_b.id
    loc_sim_id = loc_sim.id

    # Data sources
    ds_real = DataSource(
        name="Real CPCB Station",
        source_type=SourceType.API,
        is_active=True,
    )
    ds_sim = DataSource(
        name="Simulation Engine",
        source_type=SourceType.SIMULATED,
        is_active=True,
    )
    db.add_all([ds_real, ds_sim])
    db.commit()
    db.refresh(ds_real)
    db.refresh(ds_sim)

    # Seed chronological readings for loc_a (sustained elevated AQI >= 201 for 3 hours)
    base_time = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    for i in range(4):
        ts = base_time + timedelta(hours=i)
        reading = AirQualityReading(
            location_id=loc_a.id,
            source_id=ds_real.id,
            source_type=ds_real.source_type,
            timestamp=ts,
            pm25=120.0 + i * 5,
            pm10=220.0,
            no2=45.0,
            so2=20.0,
            co=1.5,
            o3=40.0,
            temperature=25.0,
            humidity=50.0,
            quality_status=QualityStatus.VALID,
        )
        db.add(reading)
        db.flush()

        aqi_val = 210 + i * 5  # 210, 215, 220, 225 -> Poor AQI
        aqi_rec = AQIRecord(
            location_id=loc_a.id,
            reading_id=reading.id,
            timestamp=ts,
            aqi=aqi_val,
            category="Poor",
            dominant_pollutant="pm25",
            status="CALCULATED",
        )
        db.add(aqi_rec)

    # Seed reading for loc_b (Satisfactory AQI = 75)
    ts_b = base_time + timedelta(hours=3)
    reading_b = AirQualityReading(
        location_id=loc_b.id,
        source_id=ds_real.id,
        source_type=ds_real.source_type,
        timestamp=ts_b,
        pm25=25.0,
        pm10=55.0,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading_b)
    db.flush()
    db.add(
        AQIRecord(
            location_id=loc_b.id,
            reading_id=reading_b.id,
            timestamp=ts_b,
            aqi=75,
            category="Satisfactory",
            dominant_pollutant="pm25",
            status="CALCULATED",
        )
    )

    # Seed SIMULATED reading for loc_sim
    reading_sim = AirQualityReading(
        location_id=loc_sim.id,
        source_id=ds_sim.id,
        source_type=ds_sim.source_type,
        timestamp=ts_b,
        pm25=280.0,
        pm10=450.0,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading_sim)
    db.flush()
    db.add(
        AQIRecord(
            location_id=loc_sim.id,
            reading_id=reading_sim.id,
            timestamp=ts_b,
            aqi=420,
            category="Severe",
            dominant_pollutant="pm25",
            status="CALCULATED",
        )
    )

    # Seed a PredictionRecord for loc_a (Predicted AQI = 230 at +3h)
    pred_rec = PredictionRecord(
        location_id=loc_a.id,
        base_timestamp=ts_b,
        target_timestamp=ts_b + timedelta(hours=3),
        horizon_hours=3,
        predicted_aqi=230.0,
        predicted_category="Poor",
        model_name="RandomForestRegressor",
        training_observations=48,
        mae=12.5,
        rmse=16.2,
        r2=0.85,
        data_sources=["API"],
        has_simulated_data=False,
    )
    db.add(pred_rec)

    db.commit()
    db.close()

    # Login tokens
    r = client.post(
        "/api/v1/auth/login",
        data={"username": "admin_alt", "password": "AdminPass123!"},
    )
    admin_token = r.json()["access_token"]

    r = client.post(
        "/api/v1/auth/login",
        data={"username": "analyst_alt", "password": "AnalystPass123!"},
    )
    analyst_token = r.json()["access_token"]

    r = client.post(
        "/api/v1/auth/login",
        data={"username": "viewer_alt", "password": "ViewerPass123!"},
    )
    viewer_token = r.json()["access_token"]

    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.clear()


# ==============================================================================
# Unit & Service Tests
# ==============================================================================

def test_aqi_threshold_trigger():
    """Verify AQI crossing threshold (225 >= 201) triggers AQI_THRESHOLD alert."""
    from backend.app.services.alert_service import evaluate_location_alerts
    from backend.app.models.alert import AlertType

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_a_id)
        # Should create an AQI_THRESHOLD alert
        threshold_alerts = [a for a in created if a.alert_type == AlertType.AQI_THRESHOLD]
        assert len(threshold_alerts) >= 1
        alt = threshold_alerts[0]
        assert alt.observed_value >= 201
        assert "201" in alt.message or alt.threshold_value == 201.0
    finally:
        db.close()


def test_aqi_below_threshold_no_alert():
    """Verify station with Satisfactory AQI (75) does not trigger Poor AQI alert."""
    from backend.app.services.alert_service import evaluate_location_alerts
    from backend.app.models.alert import AlertType

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_b_id)
        threshold_alerts = [a for a in created if a.alert_type == AlertType.AQI_THRESHOLD and a.threshold_value >= 201]
        assert len(threshold_alerts) == 0
    finally:
        db.close()


def test_sustained_aqi_trigger():
    """Verify sustained elevated AQI for >= 2 hours triggers SUSTAINED_HIGH_AQI alert."""
    from backend.app.services.alert_service import evaluate_location_alerts
    from backend.app.models.alert import AlertType

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_a_id)
        sustained = [a for a in created if a.alert_type == AlertType.SUSTAINED_HIGH_AQI]
        assert len(sustained) >= 1
        assert "sustained" in sustained[0].message.lower()
    finally:
        db.close()


def test_prediction_threshold_trigger():
    """Verify predicted AQI crossing threshold triggers PREDICTED_THRESHOLD alert with forecast labeling."""
    from backend.app.services.alert_service import evaluate_location_alerts
    from backend.app.models.alert import AlertType

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_a_id)
        predicted = [a for a in created if a.alert_type == AlertType.PREDICTED_THRESHOLD]
        assert len(predicted) >= 1
        alt = predicted[0]
        assert alt.is_prediction is True
        assert "predicted" in alt.message.lower() or "forecast" in alt.message.lower()
    finally:
        db.close()


def test_duplicate_alert_suppression():
    """Verify evaluating twice does not duplicate active alerts for the same condition."""
    from backend.app.services.alert_service import evaluate_location_alerts
    from backend.app.models.alert import Alert, AlertStatus

    db = TestingSessionLocal()
    try:
        first_run = evaluate_location_alerts(db, loc_a_id)
        initial_count = db.query(Alert).filter(Alert.location_id == loc_a_id, Alert.status == AlertStatus.ACTIVE).count()
        assert initial_count > 0

        # Second evaluation on the same state
        second_run = evaluate_location_alerts(db, loc_a_id)
        second_count = db.query(Alert).filter(Alert.location_id == loc_a_id, Alert.status == AlertStatus.ACTIVE).count()

        # Count of active alerts must NOT double
        assert second_count == initial_count
    finally:
        db.close()


def test_alert_lifecycle_and_acknowledge():
    """Verify an active alert can be acknowledged by user."""
    from backend.app.services.alert_service import evaluate_location_alerts, acknowledge_alert
    from backend.app.models.alert import AlertStatus

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_a_id)
        alert_id = created[0].id

        updated = acknowledge_alert(db, alert_id)
        assert updated.status == AlertStatus.ACKNOWLEDGED
    finally:
        db.close()


def test_alert_manual_resolve():
    """Verify an alert can be manually resolved with resolved_at timestamp populated."""
    from backend.app.services.alert_service import evaluate_location_alerts, resolve_alert
    from backend.app.models.alert import AlertStatus

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_a_id)
        alert_id = created[0].id

        resolved = resolve_alert(db, alert_id)
        assert resolved.status == AlertStatus.RESOLVED
        assert resolved.resolved_at is not None
    finally:
        db.close()


def test_provenance_preservation_simulated():
    """Verify alert on SIMULATED reading explicitly preserves source_type='SIMULATED'."""
    from backend.app.services.alert_service import evaluate_location_alerts

    db = TestingSessionLocal()
    try:
        created = evaluate_location_alerts(db, loc_sim_id)
        assert len(created) > 0
        sim_alert = created[0]
        assert sim_alert.source_type == "SIMULATED"
    finally:
        db.close()


def test_disabled_rule_not_evaluated():
    """Verify disabled alert rules do not generate alerts."""
    from backend.app.services.alert_service import ensure_default_alert_rules, evaluate_location_alerts
    from backend.app.models.alert import AlertRule

    db = TestingSessionLocal()
    try:
        # Ensure rules exist first, then disable all
        ensure_default_alert_rules(db)
        db.query(AlertRule).update({"enabled": False})
        db.commit()

        created = evaluate_location_alerts(db, loc_a_id)
        assert len(created) == 0
    finally:
        db.close()


# ==============================================================================
# REST API & RBAC Tests
# ==============================================================================

def test_api_get_rules_authenticated():
    """Authenticated users can list alert rules."""
    response = client.get(
        "/api/v1/alerts/rules",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_api_create_rule_admin_success():
    """Admin can create a new alert rule."""
    payload = {
        "name": "Custom Severe Threshold",
        "alert_type": "AQI_THRESHOLD",
        "threshold": 350.0,
        "severity": "CRITICAL",
        "enabled": True,
    }
    response = client.post(
        "/api/v1/alerts/rules",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Custom Severe Threshold"
    assert data["threshold"] == 350.0


def test_api_create_rule_analyst_forbidden():
    """Analyst cannot create alert rules (HTTP 403)."""
    payload = {
        "name": "Analyst Rule",
        "alert_type": "AQI_THRESHOLD",
        "threshold": 200.0,
        "severity": "HIGH",
    }
    response = client.post(
        "/api/v1/alerts/rules",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert response.status_code == 403


def test_api_create_rule_viewer_forbidden():
    """Viewer cannot create alert rules (HTTP 403)."""
    payload = {
        "name": "Viewer Rule",
        "alert_type": "AQI_THRESHOLD",
        "threshold": 200.0,
        "severity": "HIGH",
    }
    response = client.post(
        "/api/v1/alerts/rules",
        json=payload,
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


def test_api_evaluate_location_admin_and_analyst():
    """Admin and Analyst can trigger location alert evaluation."""
    res_admin = client.post(
        f"/api/v1/alerts/evaluate/{loc_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200

    res_analyst = client.post(
        f"/api/v1/alerts/evaluate/{loc_a_id}",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res_analyst.status_code == 200


def test_api_evaluate_location_viewer_forbidden():
    """Viewer is forbidden from triggering alert evaluation (HTTP 403)."""
    response = client.post(
        f"/api/v1/alerts/evaluate/{loc_a_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


def test_api_get_active_alerts_and_filtering():
    """Active alerts can be queried and filtered by location and severity."""
    # First evaluate with admin
    client.post(
        f"/api/v1/alerts/evaluate/{loc_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Query active alerts
    response = client.get(
        f"/api/v1/alerts/active?location_id={loc_a_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert all(a["location_id"] == loc_a_id for a in data)


def test_api_acknowledge_and_resolve_flow():
    """Admin/Analyst can acknowledge and resolve alerts."""
    # Evaluate
    client.post(
        f"/api/v1/alerts/evaluate/{loc_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Get active alert
    alerts = client.get(
        f"/api/v1/alerts/active?location_id={loc_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    alert_id = alerts[0]["id"]

    # Acknowledge with Analyst
    res_ack = client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res_ack.status_code == 200
    assert res_ack.json()["status"] == "ACKNOWLEDGED"

    # Resolve with Admin
    res_res = client.post(
        f"/api/v1/alerts/{alert_id}/resolve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "RESOLVED"
    assert res_res.json()["resolved_at"] is not None


def test_api_acknowledge_viewer_forbidden():
    """Viewer cannot acknowledge alerts (HTTP 403)."""
    # Evaluate
    client.post(
        f"/api/v1/alerts/evaluate/{loc_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    alerts = client.get(
        f"/api/v1/alerts/active?location_id={loc_a_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    alert_id = alerts[0]["id"]

    response = client.post(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


def test_api_unauthenticated_rejected():
    """Unauthenticated requests return HTTP 401."""
    response = client.get("/api/v1/alerts")
    assert response.status_code == 401
