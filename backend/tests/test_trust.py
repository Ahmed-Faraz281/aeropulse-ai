import math
import warnings
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.exceptions import StarletteDeprecationWarning

warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
warnings.filterwarnings("ignore", message=".*BlockingPortal.*")

from backend.app.core.config import settings
from backend.app.core.database import Base
from backend.app.core.security import create_access_token
from backend.app.main import app
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import Alert, AlertRule, AlertSeverity, AlertStatus, AlertType
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import ModelRegistryRecord, PredictionRecord
from backend.app.models.user import User, UserRole
from backend.app.schemas.trust import (
    DataFreshnessStatus,
    PredictionReadiness,
    StationDataFreshness,
    StationDataQuality,
    StationTrustResponse,
    SystemTrustOverview,
)
from backend.app.services.trust_service import (
    evaluate_data_freshness,
    evaluate_data_quality,
    evaluate_degraded_state,
    evaluate_prediction_trust,
    evaluate_provenance,
    get_station_trust,
    get_system_trust_overview,
)


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()

    # Create default data sources
    ds_api = DataSource(name="OpenAQ API", source_type=SourceType.API, provider="OpenAQ")
    ds_demo = DataSource(name="CPCB Demo", source_type=SourceType.DEMO, provider="CPCB")
    ds_sim = DataSource(name="Simulation Engine", source_type=SourceType.SIMULATED, provider="Software")
    ds_upload = DataSource(name="Uploaded Dataset", source_type=SourceType.UPLOADED, provider="Manual")
    session.add_all([ds_api, ds_demo, ds_sim, ds_upload])
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def auth_headers(db_session):
    def _make(role: UserRole = UserRole.VIEWER) -> Dict[str, str]:
        user = User(
            email=f"{role.value.lower()}_{datetime.now().timestamp()}@aeropulse.org",
            username=f"test_{role.value.lower()}_{datetime.now().timestamp()}",
            password_hash="testpasshash",
            role=role,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        token = create_access_token(subject=str(user.id))
        return {"Authorization": f"Bearer {token}"}
    return _make


@pytest.fixture
def client(db_session):
    from backend.app.api.deps import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_test_location(
    name: str = "Central Delhi Monitoring Station",
    city: str = "Delhi",
    state: str = "Delhi",
    country: str = "India",
    latitude: float = 28.6139,
    longitude: float = 77.2090,
    external_provider: Optional[str] = "OPENAQ",
    external_id: Optional[str] = "3001",
    is_active: bool = True,
) -> Location:
    return Location(
        name=name,
        city=city,
        state=state,
        country=country,
        latitude=latitude,
        longitude=longitude,
        external_provider=external_provider,
        external_id=external_id,
        is_active=is_active,
    )


# ==============================================================================
# Domain 1: Freshness Tests
# ==============================================================================

def test_freshness_fresh_observation():
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=1.5)
    f = evaluate_data_freshness(ts, now=now)
    assert f.status == DataFreshnessStatus.FRESH
    assert f.age_hours == 1.5
    assert f.age_minutes == 90.0
    assert "FRESH" in f.message


def test_freshness_stale_observation():
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=11.0)
    f = evaluate_data_freshness(ts, now=now)
    assert f.status == DataFreshnessStatus.STALE
    assert f.age_hours == 11.0
    assert "STALE" in f.message


def test_freshness_unavailable_missing_observation():
    f = evaluate_data_freshness(None)
    assert f.status == DataFreshnessStatus.UNAVAILABLE
    assert f.observation_timestamp is None
    assert f.age_hours is None
    assert "UNAVAILABLE" in f.message


def test_freshness_unavailable_old_observation():
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=30.0)
    f = evaluate_data_freshness(ts, now=now)
    assert f.status == DataFreshnessStatus.UNAVAILABLE
    assert f.age_hours == 30.0
    assert "UNAVAILABLE" in f.message


def test_freshness_exact_boundaries():
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    
    # Boundary: exactly 3.0h -> FRESH (<= 3.0)
    ts_3h = now - timedelta(hours=3.0)
    assert evaluate_data_freshness(ts_3h, now=now).status == DataFreshnessStatus.FRESH

    # Boundary: 3.01h -> STALE (> 3.0 and <= 24.0)
    ts_3h_1s = now - timedelta(hours=3.01)
    assert evaluate_data_freshness(ts_3h_1s, now=now).status == DataFreshnessStatus.STALE

    # Boundary: exactly 24.0h -> STALE (<= 24.0)
    ts_24h = now - timedelta(hours=24.0)
    assert evaluate_data_freshness(ts_24h, now=now).status == DataFreshnessStatus.STALE

    # Boundary: 24.01h -> UNAVAILABLE (> 24.0)
    ts_24h_1s = now - timedelta(hours=24.01)
    assert evaluate_data_freshness(ts_24h_1s, now=now).status == DataFreshnessStatus.UNAVAILABLE


def test_freshness_timezone_safety():
    # Naive timestamp should not raise TypeError
    now_aware = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    ts_naive = datetime(2026, 9, 27, 10, 0, 0)  # 2 hours before
    f = evaluate_data_freshness(ts_naive, now=now_aware)
    assert f.status == DataFreshnessStatus.FRESH
    assert f.age_hours == 2.0


# ==============================================================================
# Domain 2: Provenance Transparency Tests
# ==============================================================================

def test_provenance_api(db_session):
    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.API).first()
    reading = AirQualityReading(
        location_id=1,
        source_id=ds.id,
        source_type=SourceType.API,
        timestamp=datetime.now(timezone.utc),
    )
    reading.data_source = ds
    prov = evaluate_provenance(reading)
    assert prov.source_type == "API"
    assert "monitoring network API" in prov.notice


def test_provenance_simulated(db_session):
    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.SIMULATED).first()
    reading = AirQualityReading(
        location_id=1,
        source_id=ds.id,
        source_type=SourceType.SIMULATED,
        timestamp=datetime.now(timezone.utc),
    )
    reading.data_source = ds
    prov = evaluate_provenance(reading)
    assert prov.source_type == "SIMULATED"
    assert "Not an actual physical measurement" in prov.notice


def test_provenance_uploaded(db_session):
    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.UPLOADED).first()
    reading = AirQualityReading(
        location_id=1,
        source_id=ds.id,
        source_type=SourceType.UPLOADED,
        timestamp=datetime.now(timezone.utc),
    )
    reading.data_source = ds
    prov = evaluate_provenance(reading)
    assert prov.source_type == "UPLOADED"
    assert "dataset uploaded" in prov.notice


def test_provenance_demo(db_session):
    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.DEMO).first()
    reading = AirQualityReading(
        location_id=1,
        source_id=ds.id,
        source_type=SourceType.DEMO,
        timestamp=datetime.now(timezone.utc),
    )
    reading.data_source = ds
    prov = evaluate_provenance(reading)
    assert prov.source_type == "DEMO"
    assert "Demo seed dataset" in prov.notice


def test_provenance_never_relabels(db_session):
    # Ensure DEMO is not relabeled as API, and SIMULATED is not relabeled as API
    ds_demo = db_session.query(DataSource).filter(DataSource.source_type == SourceType.DEMO).first()
    demo_reading = AirQualityReading(location_id=1, source_id=ds_demo.id, source_type=SourceType.DEMO, timestamp=datetime.now(timezone.utc))
    demo_reading.data_source = ds_demo
    assert evaluate_provenance(demo_reading).source_type != "API"

    ds_sim = db_session.query(DataSource).filter(DataSource.source_type == SourceType.SIMULATED).first()
    sim_reading = AirQualityReading(location_id=1, source_id=ds_sim.id, source_type=SourceType.SIMULATED, timestamp=datetime.now(timezone.utc))
    sim_reading.data_source = ds_sim
    assert evaluate_provenance(sim_reading).source_type != "API"


# ==============================================================================
# Domain 3: Data Quality Tests
# ==============================================================================

def test_data_quality_complete_set(db_session):
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=1,
        source_id=1,
        source_type=SourceType.API,
        timestamp=now,
        pm25=35.0,
        pm10=70.0,
        no2=25.0,
        so2=12.0,
        co=0.8,
        o3=40.0,
        quality_status=QualityStatus.VALID,
    )
    aqi_rec = AQIRecord(
        location_id=1,
        reading_id=1,
        timestamp=now,
        aqi=95,
        category="Satisfactory",
        dominant_pollutant="pm25",
        status="CALCULATED",
        pollutant_subindices={"pm25": 95, "pm10": 70, "no2": 31, "so2": 15, "co": 8, "o3": 40},
    )
    q = evaluate_data_quality(reading, aqi_rec)
    assert q.aqi_valid is True
    assert q.available_count == 6
    assert q.completeness_pct == 100.0
    assert len(q.pollutants_missing) == 0
    assert len(q.pollutants_available) == 6
    assert q.dominant_pollutant == "pm25"
    assert len(q.pollutants_used_for_aqi) == 6


def test_data_quality_partial_set_valid_aqi(db_session):
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=1,
        source_id=1,
        source_type=SourceType.API,
        timestamp=now,
        pm25=45.0,
        pm10=80.0,
        no2=30.0,
        so2=None,
        co=None,
        o3=None,
        quality_status=QualityStatus.VALID,
    )
    aqi_rec = AQIRecord(
        location_id=1,
        reading_id=1,
        timestamp=now,
        aqi=110,
        category="Moderate",
        dominant_pollutant="pm25",
        status="CALCULATED",
        pollutant_subindices={"pm25": 110, "pm10": 80, "no2": 37},
    )
    q = evaluate_data_quality(reading, aqi_rec)
    assert q.aqi_valid is True
    assert q.available_count == 3
    assert q.completeness_pct == 50.0
    assert set(q.pollutants_available) == {"pm25", "pm10", "no2"}
    assert set(q.pollutants_missing) == {"so2", "co", "o3"}
    assert len(q.pollutants_used_for_aqi) == 3


def test_data_quality_missing_required_aqi_data():
    now = datetime.now(timezone.utc)
    # Only 1 pollutant present -> fails CPCB NAQI sufficiency rule (min 3 required)
    reading = AirQualityReading(
        location_id=1,
        source_id=1,
        source_type=SourceType.API,
        timestamp=now,
        pm25=45.0,
        pm10=None,
        no2=None,
        so2=None,
        co=None,
        o3=None,
        quality_status=QualityStatus.VALID,
    )
    q = evaluate_data_quality(reading, None)
    assert q.aqi_valid is False
    assert q.available_count == 1
    assert "pm25" in q.pollutants_available
    assert len(q.pollutants_missing) == 5


def test_data_quality_nonfinite_numeric_defense():
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=1,
        source_id=1,
        source_type=SourceType.API,
        timestamp=now,
        pm25=float("nan"),
        pm10=float("inf"),
        no2=25.0,
        quality_status=QualityStatus.WARNING,
    )
    q = evaluate_data_quality(reading, None)
    # NaN and Inf should not be treated as available pollutants
    assert "pm25" not in q.pollutants_available
    assert "pm10" not in q.pollutants_available
    assert "no2" in q.pollutants_available
    assert q.available_count == 1


# ==============================================================================
# Domain 4: Prediction Trust Tests
# ==============================================================================

def test_prediction_trust_model_unavailable(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()

    # Ensure no models exist in registry
    p_trust = evaluate_prediction_trust(db_session, loc.id)
    assert p_trust.readiness == PredictionReadiness.MODEL_UNAVAILABLE
    assert p_trust.model_available is False
    assert "No active ML model" in p_trust.reason


def test_prediction_trust_insufficient_history(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()
    # Register an active model
    model_reg = ModelRegistryRecord(
        model_id="general_aqi_h1",
        horizon_hours=1,
        artifact_path="dummy.joblib",
        training_observations=100,
        training_locations_count=2,
        features=["hour_sin"],
        data_sources=["API"],
        is_active=True,
    )
    db_session.add(model_reg)
    # Add only 2 readings (< 4 required)
    ds = db_session.query(DataSource).first()
    now = datetime.now(timezone.utc)
    db_session.add_all([
        AirQualityReading(location_id=loc.id, source_id=ds.id, source_type=SourceType.API, timestamp=now - timedelta(hours=1), pm25=20.0, quality_status=QualityStatus.VALID),
        AirQualityReading(location_id=loc.id, source_id=ds.id, source_type=SourceType.API, timestamp=now, pm25=25.0, quality_status=QualityStatus.VALID),
    ])
    db_session.commit()

    p_trust = evaluate_prediction_trust(db_session, loc.id, now=now)
    assert p_trust.readiness == PredictionReadiness.INSUFFICIENT_HISTORY
    assert p_trust.sufficient_history is False
    assert p_trust.continuous_hourly_count == 2
    assert "Insufficient continuous hourly history" in p_trust.reason


def test_prediction_trust_stale_input(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()
    model_reg = ModelRegistryRecord(
        model_id="general_aqi_h1",
        horizon_hours=1,
        artifact_path="dummy.joblib",
        training_observations=100,
        training_locations_count=2,
        features=["hour_sin"],
        data_sources=["API"],
        is_active=True,
    )
    db_session.add(model_reg)
    ds = db_session.query(DataSource).first()
    
    # 4 readings but all are from 2 days ago (> 24h old)
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    base_old = now - timedelta(days=2)
    for i in range(4):
        db_session.add(
            AirQualityReading(
                location_id=loc.id,
                source_id=ds.id,
                source_type=SourceType.API,
                timestamp=base_old + timedelta(hours=i),
                pm25=30.0,
                quality_status=QualityStatus.VALID,
            )
        )
    db_session.commit()

    p_trust = evaluate_prediction_trust(db_session, loc.id, now=now)
    assert p_trust.readiness == PredictionReadiness.STALE_INPUT
    assert p_trust.sufficient_history is True
    assert "delayed" in p_trust.reason.lower() or "stale" in p_trust.reason.lower()


def test_prediction_trust_ready(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()
    model_reg = ModelRegistryRecord(
        model_id="general_aqi_h1",
        horizon_hours=1,
        artifact_path="dummy.joblib",
        training_observations=100,
        training_locations_count=2,
        features=["hour_sin"],
        data_sources=["API"],
        is_active=True,
    )
    db_session.add(model_reg)
    ds = db_session.query(DataSource).first()
    
    now = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(4):
        db_session.add(
            AirQualityReading(
                location_id=loc.id,
                source_id=ds.id,
                source_type=SourceType.API,
                timestamp=now - timedelta(hours=3 - i),
                pm25=30.0,
                quality_status=QualityStatus.VALID,
            )
        )
    db_session.commit()

    p_trust = evaluate_prediction_trust(db_session, loc.id, now=now)
    assert p_trust.readiness == PredictionReadiness.READY
    assert p_trust.sufficient_history is True
    assert p_trust.model_available is True
    assert 1 in p_trust.active_horizons
    assert "ready" in p_trust.reason.lower()


# ==============================================================================
# Domain 5: Automation Status Reflection Tests
# ==============================================================================

def test_automation_status_reflection(db_session):
    with patch("backend.app.services.trust_service.get_automation_supervisor") as mock_sup_fn:
        mock_sup = MagicMock()
        mock_sup.is_in_backoff.return_value = False
        mock_status = MagicMock()
        mock_status.status = "IDLE"
        mock_status.enabled = True
        mock_status.paused = False
        mock_status.last_run = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
        mock_status.next_run = datetime(2026, 9, 27, 11, 15, 0, tzinfo=timezone.utc)
        mock_sup.get_status.return_value = mock_status
        mock_sup_fn.return_value = mock_sup

        overview = get_system_trust_overview(db_session)
        assert overview.automation_status == "IDLE"
        assert overview.automation_paused is False
        assert overview.last_sync == mock_status.last_run
        assert overview.next_sync == mock_status.next_run


# ==============================================================================
# Domain 6: Degraded Mode & Isolation Tests
# ==============================================================================

def test_degraded_state_openaq_backoff(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.trust_service.get_automation_supervisor") as mock_sup_fn:
        mock_sup = MagicMock()
        mock_sup.is_in_backoff.return_value = True
        mock_sup.backoff_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        mock_sup_fn.return_value = mock_sup

        state = evaluate_degraded_state(db_session, loc.id, ml_ready=True)
        assert state.is_degraded is True
        assert state.openaq_accessible is False
        assert any("rate-limited" in n for n in state.notes)


def test_degraded_state_ml_unavailable(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.trust_service.get_automation_supervisor") as mock_sup_fn:
        mock_sup = MagicMock()
        mock_sup.is_in_backoff.return_value = False
        mock_sup_fn.return_value = mock_sup

        state = evaluate_degraded_state(db_session, loc.id, ml_ready=False)
        assert state.is_degraded is True
        assert state.ml_ready is False
        assert any("ML forecasting unavailable" in n for n in state.notes)


# ==============================================================================
# Domain 7: Alert Trust & Differentiation Tests
# ==============================================================================

def test_alert_trust_types_and_statuses(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()

    now = datetime.now(timezone.utc)
    # Create real active alert
    a1 = Alert(
        location_id=loc.id,
        rule_id=1,
        alert_type=AlertType.AQI_THRESHOLD,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.ACTIVE,
        title="High AQI",
        message="AQI > 200",
        observed_value=210.0,
        threshold_value=200.0,
        detected_at=now,
    )
    # Create predicted alert
    a2 = Alert(
        location_id=loc.id,
        rule_id=2,
        alert_type=AlertType.PREDICTED_THRESHOLD,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.ACTIVE,
        title="Predicted High AQI",
        message="Forecast AQI > 200",
        observed_value=220.0,
        threshold_value=200.0,
        detected_at=now,
    )
    # Create resolved alert
    a3 = Alert(
        location_id=loc.id,
        rule_id=1,
        alert_type=AlertType.AQI_THRESHOLD,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.RESOLVED,
        title="Resolved AQI",
        message="AQI returned to normal",
        observed_value=150.0,
        threshold_value=200.0,
        detected_at=now,
    )
    db_session.add_all([a1, a2, a3])
    db_session.commit()

    assert a1.status == AlertStatus.ACTIVE
    assert a1.alert_type == AlertType.AQI_THRESHOLD
    assert a2.alert_type == AlertType.PREDICTED_THRESHOLD
    assert a3.status == AlertStatus.RESOLVED


def test_what_if_does_not_create_real_alerts(db_session):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()

    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.API).first()
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=loc.id,
        source_id=ds.id,
        source_type=SourceType.API,
        timestamp=now,
        pm25=50.0,
        pm10=100.0,
        no2=40.0,
        quality_status=QualityStatus.VALID,
    )
    db_session.add(reading)
    db_session.commit()

    initial_alerts_count = db_session.query(Alert).count()

    # What-If calculation simulation should be purely functional/stateless
    from backend.app.schemas.what_if import WhatIfSimulationRequest
    from backend.app.services.what_if_service import run_what_if_simulation

    req = WhatIfSimulationRequest(
        location_id=loc.id,
        pollutant_changes={"pm25": 50.0, "pm10": 20.0},
    )
    sim_res = run_what_if_simulation(db=db_session, request=req)
    assert sim_res.scenario.simulated_aqi is not None
    assert sim_res.scenario.provenance == "WHAT_IF / SIMULATED"

    # Verify no persistent alert records created
    post_alerts_count = db_session.query(Alert).count()
    assert post_alerts_count == initial_alerts_count


# ==============================================================================
# Domain 8: REST API Endpoints & RBAC Tests
# ==============================================================================

def test_unauthenticated_overview_rejected(client):
    res = client.get("/api/v1/trust/overview")
    assert res.status_code == 401


def test_unauthenticated_station_rejected(client):
    res = client.get("/api/v1/trust/station/1")
    assert res.status_code == 401


def test_viewer_can_get_overview(client, auth_headers):
    res = client.get("/api/v1/trust/overview", headers=auth_headers(UserRole.VIEWER))
    assert res.status_code == 200
    data = res.json()
    assert "fresh_stations_count" in data
    assert "stale_stations_count" in data
    assert "unavailable_stations_count" in data
    assert "automation_status" in data


def test_analyst_can_get_overview(client, auth_headers):
    res = client.get("/api/v1/trust/overview", headers=auth_headers(UserRole.ANALYST))
    assert res.status_code == 200


def test_admin_can_get_overview(client, auth_headers):
    res = client.get("/api/v1/trust/overview", headers=auth_headers(UserRole.ADMIN))
    assert res.status_code == 200


def test_viewer_can_get_station_trust(client, db_session, auth_headers):
    loc = make_test_location()
    db_session.add(loc)
    db_session.commit()

    res = client.get(f"/api/v1/trust/station/{loc.id}", headers=auth_headers(UserRole.VIEWER))
    assert res.status_code == 200
    data = res.json()
    assert data["location_id"] == loc.id
    assert "freshness" in data
    assert "quality" in data
    assert "provenance" in data
    assert "prediction" in data
    assert "degraded_state" in data
    assert data["freshness"]["status"] == "UNAVAILABLE"  # No reading yet


def test_station_trust_not_found_404(client, auth_headers):
    res = client.get("/api/v1/trust/station/99999", headers=auth_headers(UserRole.VIEWER))
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_station_trust_full_profile(client, db_session, auth_headers):
    loc = make_test_location(name="Bangalore Hebbal")
    db_session.add(loc)
    db_session.commit()

    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.API).first()
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=loc.id,
        source_id=ds.id,
        source_type=SourceType.API,
        timestamp=now - timedelta(minutes=45),
        pm25=42.0,
        pm10=78.0,
        no2=28.0,
        so2=14.0,
        co=0.9,
        o3=38.0,
        quality_status=QualityStatus.VALID,
    )
    db_session.add(reading)
    db_session.commit()

    aqi_rec = AQIRecord(
        location_id=loc.id,
        reading_id=reading.id,
        timestamp=reading.timestamp,
        aqi=105,
        category="Moderate",
        dominant_pollutant="pm25",
        status="CALCULATED",
        pollutant_subindices={"pm25": 105, "pm10": 78, "no2": 35},
    )
    db_session.add(aqi_rec)
    db_session.commit()

    res = client.get(f"/api/v1/trust/station/{loc.id}", headers=auth_headers(UserRole.ADMIN))
    assert res.status_code == 200
    data = res.json()
    assert data["location_name"] == "Bangalore Hebbal"
    assert data["current_aqi"] == 105
    assert data["aqi_category"] == "Moderate"
    assert data["freshness"]["status"] == "FRESH"
    assert data["quality"]["aqi_valid"] is True
    assert data["quality"]["completeness_pct"] == 100.0
    assert data["provenance"]["source_type"] == "API"


def test_freshness_future_timestamp_treated_as_fresh():
    # In case of minor clock drift, future timestamp should have age_hours >= 0.0 and FRESH
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    f = evaluate_data_freshness(future_time)
    assert f.status == DataFreshnessStatus.FRESH
    assert f.age_hours >= 0.0


def test_evaluate_provenance_none_reading():
    p = evaluate_provenance(None)
    assert p.source_type == "UNKNOWN"
    assert "telemetry" in p.notice.lower() or "dataset" in p.notice.lower()


def test_data_quality_missing_both_pm():
    # 4 gases present, but neither PM2.5 nor PM10 present -> CPCB requires at least 1 PM
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=1,
        source_id=1,
        source_type=SourceType.API,
        timestamp=now,
        pm25=None,
        pm10=None,
        no2=25.0,
        so2=12.0,
        co=0.8,
        o3=40.0,
        quality_status=QualityStatus.VALID,
    )
    q = evaluate_data_quality(reading, None)
    assert q.aqi_valid is False
    assert q.available_count == 4
    assert q.aqi_status == "INSUFFICIENT_DATA"


def test_prediction_trust_zero_readings(db_session):
    loc = make_test_location()
    db_session.add(loc)
    model_reg = ModelRegistryRecord(
        model_id="general_aqi_h1",
        horizon_hours=1,
        artifact_path="dummy.joblib",
        training_observations=100,
        training_locations_count=2,
        features=["hour_sin"],
        data_sources=["API"],
        is_active=True,
    )
    db_session.add(model_reg)
    db_session.commit()

    trust = evaluate_prediction_trust(db_session, loc.id, None)
    assert trust.readiness == PredictionReadiness.INSUFFICIENT_HISTORY
    assert trust.sufficient_history is False
    assert trust.continuous_hourly_count == 0
    assert trust.model_available is True


def test_system_trust_overview_mixed_stations(client, db_session, auth_headers):
    # Create 3 stations with unique external IDs
    loc1 = make_test_location(name="Fresh Station", external_id="8001")
    loc2 = make_test_location(name="Stale Station", external_id="8002")
    loc3 = make_test_location(name="Empty Station", external_id="8003")
    db_session.add_all([loc1, loc2, loc3])
    db_session.commit()

    ds = db_session.query(DataSource).filter(DataSource.source_type == SourceType.API).first()
    now = datetime.now(timezone.utc)

    # loc1 has reading 1 hr old -> FRESH
    r1 = AirQualityReading(
        location_id=loc1.id,
        source_id=ds.id,
        source_type=SourceType.API,
        timestamp=now - timedelta(hours=1),
        pm25=30.0,
        pm10=60.0,
        no2=20.0,
        quality_status=QualityStatus.VALID,
    )
    # loc2 has reading 10 hrs old -> STALE
    r2 = AirQualityReading(
        location_id=loc2.id,
        source_id=ds.id,
        source_type=SourceType.API,
        timestamp=now - timedelta(hours=10),
        pm25=30.0,
        pm10=60.0,
        no2=20.0,
        quality_status=QualityStatus.VALID,
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    res = client.get("/api/v1/trust/overview", headers=auth_headers(UserRole.VIEWER))
    assert res.status_code == 200
    data = res.json()
    assert data["total_locations"] >= 3
    assert data["fresh_stations_count"] >= 1
    assert data["stale_stations_count"] >= 1
    assert data["unavailable_stations_count"] >= 1


def test_station_trust_inactive_location(client, db_session, auth_headers):
    loc = make_test_location(name="Inactive Station", external_id="9991")
    loc.is_active = False
    db_session.add(loc)
    db_session.commit()

    res = client.get(f"/api/v1/trust/station/{loc.id}", headers=auth_headers(UserRole.VIEWER))
    assert res.status_code == 200
    data = res.json()
    assert data["is_active"] is False
    assert data["freshness"]["status"] == "UNAVAILABLE"


def test_data_quality_all_null_reading():
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=1,
        source_id=1,
        source_type=SourceType.API,
        timestamp=now,
        pm25=None,
        pm10=None,
        no2=None,
        so2=None,
        co=None,
        o3=None,
        quality_status=QualityStatus.VALID,
    )
    q = evaluate_data_quality(reading, None)
    assert q.aqi_valid is False
    assert q.available_count == 0
    assert q.completeness_pct == 0.0
    assert len(q.pollutants_missing) == 6
    assert len(q.pollutants_available) == 0



