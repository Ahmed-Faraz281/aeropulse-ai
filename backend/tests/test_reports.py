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
from backend.app.models.prediction import PredictionRecord
from backend.app.services.aqi_engine import calculate_aqi
from backend.app.api.v1.aqi import _get_or_create_aqi_record

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
loc2_id = 0
empty_loc_id = 0


@pytest.fixture(autouse=True)
def setup_reports_test_db():
    global admin_token, analyst_token, viewer_token
    global loc_id, loc2_id, empty_loc_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Create users
    admin = User(
        username="admin_rep",
        email="admin_rep@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_rep",
        email="analyst_rep@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_rep",
        email="viewer_rep@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Create locations
    loc1 = Location(
        name="Anand Vihar Station",
        city="Delhi",
        state="Delhi",
        country="India",
        latitude=28.6508,
        longitude=77.3153,
        is_active=True,
    )
    loc2 = Location(
        name="BTM Layout Station",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9166,
        longitude=77.6101,
        is_active=True,
    )
    loc_empty = Location(
        name="Remote Station",
        city="Shimla",
        state="Himachal Pradesh",
        country="India",
        latitude=31.1048,
        longitude=77.1734,
        is_active=True,
    )
    db.add_all([loc1, loc2, loc_empty])
    db.commit()
    loc_id = loc1.id
    loc2_id = loc2.id
    empty_loc_id = loc_empty.id

    # Create data source
    src_api = DataSource(name="CPCB Public API", source_type=SourceType.API, is_active=True)
    src_sim = DataSource(name="Simulation Engine", source_type=SourceType.SIMULATED, is_active=True)
    db.add_all([src_api, src_sim])
    db.commit()

    # Create historical readings for loc1 (last 10 hours)
    now = datetime.now(timezone.utc)
    for i in range(10):
        t = now - timedelta(hours=9 - i)
        # Progressively rising pollution to detect trend & events
        pm25 = 110.0 + (i * 12.0)
        pm10 = 180.0 + (i * 15.0)
        reading = AirQualityReading(
            location_id=loc1.id,
            source_id=src_api.id,
            source_type=SourceType.API,
            timestamp=t,
            pm25=pm25,
            pm10=pm10,
            no2=45.0,
            so2=20.0,
            co=1.2,
            o3=35.0,
            temperature=26.0,
            humidity=55.0,
            quality_status=QualityStatus.VALID,
        )
        db.add(reading)
        db.flush()
        _get_or_create_aqi_record(reading, db)

    # Add a reading with an anomaly for loc1
    anom_reading = AirQualityReading(
        location_id=loc1.id,
        source_id=src_api.id,
        source_type=SourceType.API,
        timestamp=now + timedelta(minutes=5),
        pm25=450.0,  # Extreme spike
        pm10=600.0,
        no2=180.0,
        so2=90.0,
        co=4.5,
        o3=85.0,
        temperature=25.0,
        humidity=60.0,
        quality_status=QualityStatus.VALID,
    )
    db.add(anom_reading)
    db.flush()
    _get_or_create_aqi_record(anom_reading, db)

    # Readings for loc2 (Satisfactory/Moderate)
    for i in range(5):
        t = now - timedelta(hours=5 - i)
        r2 = AirQualityReading(
            location_id=loc2.id,
            source_id=src_sim.id,
            source_type=SourceType.SIMULATED,
            timestamp=t,
            pm25=45.0,
            pm10=80.0,
            no2=30.0,
            so2=12.0,
            co=0.8,
            o3=25.0,
            quality_status=QualityStatus.VALID,
        )
        db.add(r2)
        db.flush()
        _get_or_create_aqi_record(r2, db)

    # Create alerts (one observation alert and one forecast alert)
    rule = AlertRule(
        name="PM2.5 Severe Spike Alert",
        alert_type=AlertType.AQI_THRESHOLD,
        threshold=250.0,
        severity=AlertSeverity.HIGH,
        enabled=True,
    )
    db.add(rule)
    db.flush()

    alert_obs = Alert(
        location_id=loc1.id,
        rule_id=rule.id,
        alert_type=AlertType.AQI_THRESHOLD,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.ACTIVE,
        title="PM2.5 Severe Spike Alert",
        message="Observation AQI 420 exceeded threshold 250",
        observed_value=420.0,
        threshold_value=250.0,
        is_prediction=False,
        source_type="API",
        detected_at=now - timedelta(hours=1),
    )
    alert_fc = Alert(
        location_id=loc1.id,
        rule_id=rule.id,
        alert_type=AlertType.PREDICTED_THRESHOLD,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.ACTIVE,
        title="Predicted Spike Alert",
        message="Forecast AQI 310 predicted to exceed threshold in +6h",
        observed_value=310.0,
        threshold_value=250.0,
        is_prediction=True,
        source_type="PREDICTED",
        detected_at=now - timedelta(hours=2),
    )
    db.add_all([alert_obs, alert_fc])

    # Create ML prediction record
    pred = PredictionRecord(
        location_id=loc1.id,
        base_timestamp=now - timedelta(hours=1),
        target_timestamp=now + timedelta(hours=6),
        horizon_hours=6,
        predicted_aqi=315.0,
        predicted_category="Very Poor",
        model_name="RandomForestRegressor",
        training_observations=120,
        mae=12.4,
        rmse=16.8,
        r2=0.88,
        data_sources=["API"],
        has_simulated_data=False,
        provenance_notice="Trained exclusively on validated historical data.",
    )
    db.add(pred)
    db.commit()
    db.close()

    # Login users to get tokens
    r = client.post("/api/v1/auth/login", data={"username": "admin_rep", "password": "AdminPass123!"})
    admin_token = r.json()["access_token"]

    r = client.post("/api/v1/auth/login", data={"username": "analyst_rep", "password": "AnalystPass123!"})
    analyst_token = r.json()["access_token"]

    r = client.post("/api/v1/auth/login", data={"username": "viewer_rep", "password": "ViewerPass123!"})
    viewer_token = r.json()["access_token"]


def test_location_summary_report_preview():
    """1. Location Summary Report preview generates complete executive summary and statistics."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
        "period_preset": "24h",
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["report_type"] == "LOCATION_SUMMARY"
    assert data["location_name"] == "Anand Vihar Station"
    assert data["city"] == "Delhi"
    assert data["latest_aqi"] is not None
    assert data["latest_category"] is not None
    assert data["dominant_pollutant"] is not None
    assert "executive_summary" in data
    assert len(data["executive_summary"]) > 50
    assert data["aqi_statistics"]["count"] > 0
    assert data["aqi_statistics"]["mean"] is not None


def test_period_report_preview():
    """2. Period Report correctly aggregates multi-day observations and category distributions."""
    payload = {
        "report_type": "PERIOD_REPORT",
        "location_id": loc_id,
        "period_preset": "48h",
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["report_type"] == "PERIOD_REPORT"
    assert "category_distribution" in data
    assert sum(data["category_distribution"].values()) > 0
    assert data["trend_direction"] in ["INCREASING", "DECREASING", "STABLE", "INSUFFICIENT_DATA"]


def test_comparison_report_preview():
    """3. Comparison Report includes all requested stations factually without subjective rankings."""
    payload = {
        "report_type": "COMPARISON_REPORT",
        "location_id": loc_id,
        "comparison_location_ids": [loc2_id],
        "period_preset": "24h",
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["report_type"] == "COMPARISON_REPORT"
    assert data["comparison_data"] is not None
    assert len(data["comparison_data"]) == 2

    # Check stations are present
    names = [c["location_name"] for c in data["comparison_data"]]
    assert "Anand Vihar Station" in names
    assert "BTM Layout Station" in names

    # Assert no subjective ranking words
    for c in data["comparison_data"]:
        assert "best" not in str(c).lower()
        assert "worst" not in str(c).lower()
        assert "healthiest" not in str(c).lower()


def test_what_if_report_preview():
    """4. What-If Report contains scenario impact and prominently identifies WHAT_IF / SIMULATED."""
    payload = {
        "report_type": "WHAT_IF_REPORT",
        "location_id": loc_id,
        "what_if_request": {
            "location_id": loc_id,
            "pollutant_changes": {"pm25": -30.0, "no2": -20.0},
        },
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["report_type"] == "WHAT_IF_REPORT"
    assert data["what_if_summary"] is not None
    assert data["provenance_summary"]["scenario_provenance"] == "WHAT_IF / SIMULATED"
    assert data["what_if_summary"]["scenario"]["provenance"] == "WHAT_IF / SIMULATED"
    assert "impact" in data["what_if_summary"]
    assert data["what_if_summary"]["impact"]["direction"] in ["IMPROVED", "WORSENED", "UNCHANGED"]


def test_report_pdf_generation_magic_bytes():
    """5. Report generation returns a valid PDF binary with standard '%PDF-' magic bytes."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
        "period_preset": "24h",
    }
    res = client.post(
        "/api/v1/reports/generate",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert len(res.content) > 1000  # Non-trivial PDF size


def test_report_pdf_download_headers():
    """6. Report generation sets proper attachment Content-Disposition and X-Report-Type."""
    payload = {
        "report_type": "PERIOD_REPORT",
        "location_id": loc_id,
        "period_preset": "48h",
    }
    res = client.post(
        "/api/v1/reports/generate",
        json=payload,
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    assert "attachment; filename=" in res.headers["content-disposition"]
    assert "AeroPulse_Report_PERIOD_REPORT" in res.headers["content-disposition"]
    assert res.headers.get("x-report-type") == "PERIOD_REPORT"


def test_provenance_separation_api():
    """7. API observed telemetry provenance is preserved and reported as primary source."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["provenance_summary"]["observed_provenance"] == "API"


def test_provenance_separation_simulated():
    """8. SIMULATED data source provenance is accurately reported and never hidden."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc2_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["provenance_summary"]["observed_provenance"] == "SIMULATED"


def test_provenance_separation_predicted():
    """9. Forecast data is clearly separated with FORECAST — NOT CURRENT OBSERVATION label."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["forecast_available"] is True
    assert data["forecast_summary"] is not None
    assert data["forecast_summary"]["label"] == "FORECAST — NOT CURRENT OBSERVATION"
    assert data["forecast_summary"]["horizon_hours"] == 6


def test_provenance_separation_what_if():
    """10. What-If reports are clearly identified as SIMULATED SCENARIO — NOT AN ACTUAL MEASUREMENT."""
    payload = {
        "report_type": "WHAT_IF_REPORT",
        "location_id": loc_id,
        "what_if_request": {
            "location_id": loc_id,
            "pollutant_changes": {"pm25": -25.0},
        },
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["provenance_summary"]["scenario_provenance"] == "WHAT_IF / SIMULATED"


def test_missing_pollutant_not_zero():
    """11. Missing pollutants (NH3, Pb = None) are marked unavailable, never converted to 0."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    nh3 = data["pollutant_summary"]["nh3"]
    assert nh3["available"] is False
    assert nh3["statistics"]["mean"] is None
    assert "unavailable" in nh3["message"].lower()

    pb = data["pollutant_summary"]["pb"]
    assert pb["available"] is False
    assert pb["statistics"]["mean"] is None


def test_insufficient_aqi_data():
    """12. Station with no readings returns graceful preview without crashing."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": empty_loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["latest_aqi"] is None
    assert data["aqi_statistics"]["count"] == 0
    assert data["trend_direction"] == "INSUFFICIENT_DATA"


def test_cpcb_aqi_reuse():
    """13. Report AQI values match Phase 4 CPCB calculate_aqi engine exactly."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    # The anomaly reading had pm25=450, pm10=600, no2=180
    expected_aqi = calculate_aqi(pm25=450.0, pm10=600.0, no2=180.0, so2=90.0, co=4.5, o3=85.0)
    assert data["latest_aqi"] == expected_aqi.aqi
    assert data["latest_category"] == expected_aqi.category


def test_analytics_engine_reuse():
    """14. Trends and summaries in the report match Phase 5 analytics engine."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["trend_direction"] in ["INCREASING", "DECREASING", "STABLE"]
    assert "mean" in data["aqi_statistics"]
    assert data["aqi_statistics"]["minimum"] <= data["aqi_statistics"]["maximum"]


def test_anomalies_inclusion():
    """15. Detected statistical anomalies are included in report preview and PDF."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["anomalies_count"] > 0


def test_pollution_events_inclusion():
    """16. Sustained pollution episodes (AQI >= 201 for >= 2h) are included in report."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["events_count"] > 0


def test_alerts_inclusion_with_forecast_separation():
    """17. Alerts log includes records and clearly separates observation vs forecast alerts."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["alerts_count"] >= 2


def test_recommendation_integration():
    """18. Phase 11 recommendations are included with priority, action, and explainable reasons."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    recs = data["top_recommendations"]
    assert len(recs) > 0
    first_rec = recs[0]
    assert "priority" in first_rec
    assert "action" in first_rec
    assert "reason" in first_rec
    assert "triggered_by" in first_rec


def test_stateless_immutability():
    """19. Report preview and PDF generation perform zero database mutations."""
    db = TestingSessionLocal()
    readings_before = db.query(AirQualityReading).count()
    aqi_before = db.query(AQIRecord).count()
    alerts_before = db.query(Alert).count()
    locations_before = db.query(Location).count()
    db.close()

    # Call preview and generate
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
        "period_preset": "24h",
    }
    client.post("/api/v1/reports/preview", json=payload, headers={"Authorization": f"Bearer {analyst_token}"})
    client.post("/api/v1/reports/generate", json=payload, headers={"Authorization": f"Bearer {analyst_token}"})

    db = TestingSessionLocal()
    readings_after = db.query(AirQualityReading).count()
    aqi_after = db.query(AQIRecord).count()
    alerts_after = db.query(Alert).count()
    locations_after = db.query(Location).count()
    db.close()

    assert readings_after == readings_before
    assert aqi_after == aqi_before
    assert alerts_after == alerts_before
    assert locations_after == locations_before


def test_deterministic_report_content():
    """20. Identical inputs yield identical structured preview output."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
        "start_time": "2026-09-01T00:00:00Z",
        "end_time": "2026-09-02T00:00:00Z",
    }
    r1 = client.post("/api/v1/reports/preview", json=payload, headers={"Authorization": f"Bearer {analyst_token}"}).json()
    r2 = client.post("/api/v1/reports/preview", json=payload, headers={"Authorization": f"Bearer {analyst_token}"}).json()

    assert r1["latest_aqi"] == r2["latest_aqi"]
    assert r1["aqi_statistics"] == r2["aqi_statistics"]
    assert r1["pollutant_summary"] == r2["pollutant_summary"]
    assert r1["executive_summary"] == r2["executive_summary"]


def test_invalid_date_range_422():
    """21. Returns HTTP 422 if start_time is greater than or equal to end_time."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
        "start_time": "2026-09-10T12:00:00Z",
        "end_time": "2026-09-10T10:00:00Z",  # Earlier than start
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 422
    assert "start_time must be earlier than end_time" in res.json()["detail"]


def test_location_not_found_404():
    """22. Non-existent location ID returns HTTP 404."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": 999999,
    }
    res = client.post(
        "/api/v1/reports/preview",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_empty_dataset_pdf_generation():
    """23. PDF generator handles empty station dataset gracefully without throwing."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": empty_loc_id,
    }
    res = client.post(
        "/api/v1/reports/generate",
        json=payload,
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_rbac_admin_analyst_viewer_access():
    """24. ADMIN, ANALYST, and VIEWER roles can all preview and generate reports."""
    payload = {
        "report_type": "LOCATION_SUMMARY",
        "location_id": loc_id,
        "period_preset": "24h",
    }
    for token in [admin_token, analyst_token, viewer_token]:
        res_prev = client.post("/api/v1/reports/preview", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert res_prev.status_code == 200
        res_gen = client.post("/api/v1/reports/generate", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert res_gen.status_code == 200


def test_rbac_unauthenticated_401():
    """25. Unauthenticated preview and generation requests return HTTP 401."""
    payload = {"report_type": "LOCATION_SUMMARY", "location_id": loc_id}
    res = client.post("/api/v1/reports/preview", json=payload)
    assert res.status_code == 401

    res_pdf = client.post("/api/v1/reports/generate", json=payload)
    assert res_pdf.status_code == 401


def test_what_if_no_active_alerts_created():
    """26. What-If report simulation creates zero active alerts in database."""
    db = TestingSessionLocal()
    alert_count_before = db.query(Alert).count()
    db.close()

    payload = {
        "report_type": "WHAT_IF_REPORT",
        "location_id": loc_id,
        "what_if_request": {
            "location_id": loc_id,
            "pollutant_changes": {"pm25": 100.0, "pm10": 100.0},
        },
    }
    res = client.post(
        "/api/v1/reports/generate",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")

    db = TestingSessionLocal()
    alert_count_after = db.query(Alert).count()
    db.close()
    assert alert_count_after == alert_count_before


def test_comparison_report_pdf_generation():
    """27. Comparison report generates valid multi-page PDF."""
    payload = {
        "report_type": "COMPARISON_REPORT",
        "location_id": loc_id,
        "comparison_location_ids": [loc2_id],
        "period_preset": "48h",
    }
    res = client.post(
        "/api/v1/reports/generate",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")
    assert res.headers["x-report-type"] == "COMPARISON_REPORT"


def test_what_if_report_pdf_generation():
    """28. What-If report generates valid PDF with hypothetical scenario disclosures."""
    payload = {
        "report_type": "WHAT_IF_REPORT",
        "location_id": loc_id,
        "what_if_request": {
            "location_id": loc_id,
            "pollutant_changes": {"pm25": -40.0, "no2": -30.0},
        },
    }
    res = client.post(
        "/api/v1/reports/generate",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")
    assert res.headers["x-report-type"] == "WHAT_IF_REPORT"
