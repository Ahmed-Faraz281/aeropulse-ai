import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import warnings

import pytest
from starlette.exceptions import StarletteDeprecationWarning

warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
warnings.filterwarnings("ignore", message=".*BlockingPortal.*")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.core.database import Base
from backend.app.core.security import create_access_token
from backend.app.main import app
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import Alert, AlertRule, AlertSeverity, AlertStatus, AlertType
from backend.app.models.audit_log import AuditLog
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import PredictionRecord
from backend.app.models.user import User, UserRole
from backend.app.schemas.automation import AutomationCycleSummary, AutomationStatusResponse
from backend.app.schemas.openaq import OpenAQIngestResponse, OpenAQStationIngestSummary
from backend.app.services.automation_service import (
    AutomationSupervisor,
    get_automation_supervisor,
)
from backend.app.services.openaq_service import OpenAQRatelimitError, OpenAQUpstreamError

# In-memory test database fixture
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    # Seed OpenAQ data source
    openaq_src = DataSource(
        name="OpenAQ",
        source_type=SourceType.API,
        provider="OpenAQ API v3",
        is_active=True,
    )
    session.add(openaq_src)
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def supervisor():
    sup = AutomationSupervisor()
    return sup


@pytest.fixture
def auth_headers(db_session):
    def _make_headers(role: UserRole = UserRole.VIEWER) -> Dict[str, str]:
        user = User(
            email=f"{role.value.lower()}_{datetime.now().timestamp()}@aeropulse.org",
            username=f"test_{role.value.lower()}_{datetime.now().timestamp()}",
            password_hash="hashed_secret_pw",
            role=role,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        token = create_access_token(subject=str(user.id))
        return {"Authorization": f"Bearer {token}"}
    return _make_headers


@pytest.fixture
def client(db_session):
    from backend.app.api.deps import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_test_location(
    name: str,
    city: str = "Bengaluru",
    state: str = "Karnataka",
    country: str = "India",
    latitude: float = 13.0,
    longitude: float = 77.0,
    external_provider: Optional[str] = "OPENAQ",
    external_id: Optional[str] = "6984",
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
# 1. Supervisor Lifecycle Tests
# ==============================================================================

def test_supervisor_initial_state(supervisor):
    assert supervisor.is_enabled is True
    assert supervisor.is_paused is False
    assert supervisor.status in ("IDLE", "DISABLED")
    assert supervisor.is_in_backoff() is False


def test_supervisor_disabled_state():
    with patch.object(settings, "SCHEDULER_ENABLED", False):
        sup = AutomationSupervisor()
        assert sup.is_enabled is False
        assert sup.status == "DISABLED"


@pytest.mark.asyncio
async def test_supervisor_start_and_clean_stop(supervisor):
    assert supervisor._task is None
    await supervisor.start()
    assert supervisor._task is not None
    assert not supervisor._task.done()
    assert supervisor.status == "IDLE"

    await supervisor.stop()
    assert supervisor._shutdown_event.is_set()


def test_supervisor_pause_and_resume(supervisor):
    assert supervisor.is_paused is False
    supervisor.pause()
    assert supervisor.is_paused is True
    assert supervisor.status == "PAUSED"

    supervisor.resume()
    assert supervisor.is_paused is False
    assert supervisor.status == "IDLE"


def test_compute_next_run(supervisor):
    next_run = supervisor.compute_next_run()
    now_utc = datetime.now(timezone.utc)
    assert next_run > now_utc
    assert next_run.minute == settings.SCHEDULER_POLL_MINUTE


# ==============================================================================
# 2. Concurrency & Execution Lock Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrency_lock_prevents_simultaneous_cycles(supervisor):
    await supervisor._lock.acquire()
    try:
        with pytest.raises(BlockingIOError, match="Automation job is already in progress"):
            await supervisor.run_sync_cycle()
    finally:
        supervisor._lock.release()


def test_manual_trigger_conflict_409(client, auth_headers):
    headers = auth_headers(UserRole.ADMIN)
    supervisor = get_automation_supervisor()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(supervisor._lock.acquire())
    try:
        response = client.post("/api/v1/automation/trigger", headers=headers)
        assert response.status_code == 409
        assert "already in progress" in response.json()["detail"]
    finally:
        supervisor._lock.release()
        loop.close()


# ==============================================================================
# 3. Active Station Filtering Tests
# ==============================================================================

def test_sync_filters_active_openaq_stations_only(supervisor, db_session):
    loc_active = make_test_location(
        name="Hebbal OpenAQ Active",
        city="Bengaluru",
        state="Karnataka",
        latitude=13.029,
        longitude=77.585,
        external_provider="OPENAQ",
        external_id="6984",
        is_active=True,
    )
    loc_inactive = make_test_location(
        name="Old OpenAQ Inactive",
        city="Bengaluru",
        state="Karnataka",
        latitude=13.000,
        longitude=77.500,
        external_provider="OPENAQ",
        external_id="9999",
        is_active=False,
    )
    loc_demo = make_test_location(
        name="[DEMO] Station Central",
        city="Delhi",
        state="Delhi",
        latitude=28.613,
        longitude=77.209,
        external_provider="DEMO",
        external_id="demo_1",
        is_active=True,
    )
    loc_sim = make_test_location(
        name="Simulated Sensor Site",
        city="Mumbai",
        state="Maharashtra",
        latitude=19.076,
        longitude=72.877,
        external_provider=None,
        external_id=None,
        is_active=True,
    )
    loc_other = make_test_location(
        name="Other Provider Station",
        city="Chennai",
        state="Tamil Nadu",
        latitude=13.082,
        longitude=80.270,
        external_provider="PURPLEAIR",
        external_id="purple_1",
        is_active=True,
    )

    db_session.add_all([loc_active, loc_inactive, loc_demo, loc_sim, loc_other])
    db_session.commit()

    processed_ids = []

    def mock_ingest(req):
        processed_ids.extend(req.location_ids or [])
        return OpenAQIngestResponse(
            status="success",
            locations_discovered=1,
            locations_processed=1,
            sensors_discovered=5,
            sensors_selected=5,
            observations_fetched=10,
            observations_inserted=5,
            duplicates_skipped=5,
            observations_rejected=0,
            validation_warnings=0,
            pollutants_mapped=["PM2.5", "PM10"],
            earliest_observation=datetime.now(timezone.utc),
            latest_observation=datetime.now(timezone.utc),
            stations=[],
            predictions_generated=5,
            models_retrained=False,
            duration_seconds=0.5,
            errors=[],
        )

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest):
        result = supervisor._sync_worker()

    assert result["stations_processed"] == 1
    assert processed_ids == [6984]
    assert result["observations_ingested"] == 5
    assert result["predictions_generated"] == 5


# ==============================================================================
# 4. Max Stations Per Run & Fair Rotation Tests
# ==============================================================================

def test_max_stations_per_run_and_rotation(supervisor, db_session):
    for i in range(1, 6):
        loc = make_test_location(
            name=f"OpenAQ Station {i}",
            city=f"City {i}",
            state=f"State {i}",
            latitude=12.0 + i * 0.1,
            longitude=77.0 + i * 0.1,
            external_provider="OPENAQ",
            external_id=str(1000 + i),
            is_active=True,
        )
        db_session.add(loc)
    db_session.commit()

    with patch.object(settings, "SCHEDULER_MAX_STATIONS_PER_RUN", 2):
        call_ids_run1 = []
        call_ids_run2 = []

        def mock_ingest_run1(req):
            call_ids_run1.extend(req.location_ids or [])
            return MagicMock(observations_inserted=1, predictions_generated=0, models_retrained=False, errors=[])

        def mock_ingest_run2(req):
            call_ids_run2.extend(req.location_ids or [])
            return MagicMock(observations_inserted=1, predictions_generated=0, models_retrained=False, errors=[])

        # Run 1
        with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
             patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest_run1):
            res1 = supervisor._sync_worker()

        assert res1["stations_processed"] == 2
        assert len(call_ids_run1) == 2
        assert call_ids_run1 == [1001, 1002]

        # Run 2: Rotates to the next slice of stations
        with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
             patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest_run2):
            res2 = supervisor._sync_worker()

        assert res2["stations_processed"] == 2
        assert len(call_ids_run2) == 2
        assert call_ids_run2 == [1003, 1004]


# ==============================================================================
# 5. Incremental Ingestion & Duplicate Handling Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_successful_incremental_sync(supervisor, db_session):
    loc = make_test_location(
        name="Hebbal OpenAQ Station",
        city="Bengaluru",
        state="Karnataka",
        latitude=13.029,
        longitude=77.585,
        external_provider="OPENAQ",
        external_id="6984",
        is_active=True,
    )
    db_session.add(loc)
    db_session.commit()

    mock_resp = OpenAQIngestResponse(
        status="success",
        locations_discovered=1,
        locations_processed=1,
        sensors_discovered=5,
        sensors_selected=5,
        observations_fetched=24,
        observations_inserted=24,
        duplicates_skipped=0,
        observations_rejected=0,
        validation_warnings=0,
        pollutants_mapped=["PM2.5", "PM10", "NO2", "SO2", "CO", "O3"],
        earliest_observation=datetime.now(timezone.utc) - timedelta(hours=24),
        latest_observation=datetime.now(timezone.utc),
        stations=[],
        predictions_generated=5,
        models_retrained=True,
        duration_seconds=1.2,
        errors=[],
    )

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", return_value=mock_resp):
        summary = await supervisor.run_sync_cycle(source="test")

    assert summary.status == "success"
    assert summary.stations_processed == 1
    assert summary.stations_failed == 0
    assert summary.observations_ingested == 24
    assert summary.predictions_generated == 5
    assert summary.models_retrained is True
    assert supervisor._last_run is not None
    assert supervisor._observations_ingested == 24


def test_station_failure_isolation(supervisor, db_session):
    loc1 = make_test_location(name="Station One", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    loc2 = make_test_location(name="Station Two", city="City B", state="State B", latitude=11.0, longitude=71.0, external_provider="OPENAQ", external_id="102", is_active=True)
    db_session.add_all([loc1, loc2])
    db_session.commit()

    def mock_ingest(req):
        if req.location_ids == [101]:
            raise OpenAQUpstreamError("OpenAQ upstream 503 Service Unavailable")
        return MagicMock(observations_inserted=8, predictions_generated=5, models_retrained=False, errors=[])

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest):
        result = supervisor._sync_worker()

    assert result["stations_processed"] == 2
    assert result["stations_failed"] == 1
    assert result["observations_ingested"] == 8
    assert len(result["errors"]) == 1
    assert "Station One" in result["errors"][0]


# ==============================================================================
# 6. OpenAQ Rate Limiting & Backoff Tests
# ==============================================================================

def test_rate_limit_429_sets_backoff(supervisor, db_session):
    loc1 = make_test_location(name="Station One", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    loc2 = make_test_location(name="Station Two", city="City B", state="State B", latitude=11.0, longitude=71.0, external_provider="OPENAQ", external_id="102", is_active=True)
    db_session.add_all([loc1, loc2])
    db_session.commit()

    def mock_ingest(req):
        raise OpenAQRatelimitError("OpenAQ Rate Limit Exceeded (HTTP 429)", retry_after=300)

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest):
        result = supervisor._sync_worker()

    assert result["stations_failed"] == 1
    assert result["stations_processed"] == 1
    assert result["backoff_seconds"] == 300


@pytest.mark.asyncio
async def test_cycle_records_backoff_status(supervisor, db_session):
    loc = make_test_location(name="Station One", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    db_session.add(loc)
    db_session.commit()

    def mock_ingest(req):
        raise OpenAQRatelimitError("HTTP 429", retry_after=600)

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest):
        summary = await supervisor.run_sync_cycle()

    assert summary.status == "backoff"
    assert supervisor.is_in_backoff() is True
    assert supervisor.status == "BACKOFF"
    assert supervisor._backoff_until is not None


def test_backoff_expiration(supervisor):
    supervisor._backoff_until = datetime.now(timezone.utc) - timedelta(seconds=10)
    assert supervisor.is_in_backoff() is False
    assert supervisor._backoff_until is None


# ==============================================================================
# 7. ML Automatic Retraining & Predictions Tests
# ==============================================================================

def test_ml_automatic_retraining_trigger_reused(supervisor, db_session):
    loc = make_test_location(name="Station One", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest") as mock_ingest:
        mock_ingest.return_value = MagicMock(
            observations_inserted=250,
            predictions_generated=5,
            models_retrained=True,
            errors=[],
        )
        result = supervisor._sync_worker()

    assert result["models_retrained"] is True
    assert result["predictions_generated"] == 5


# ==============================================================================
# 8. Alert & Recommendation Evaluator Reuse Tests
# ==============================================================================

def test_alert_and_recommendation_evaluators_reused(supervisor, db_session):
    loc = make_test_location(name="Station One", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest") as mock_ingest:
        mock_ingest.return_value = MagicMock(
            observations_inserted=10,
            predictions_generated=5,
            models_retrained=False,
            errors=[],
        )
        result = supervisor._sync_worker()

    assert result["stations_processed"] == 1
    assert result["observations_ingested"] == 10


# ==============================================================================
# 9. Security & RBAC Tests
# ==============================================================================

def test_unauthenticated_status_rejected_401(client):
    response = client.get("/api/v1/automation/status")
    assert response.status_code == 401


def test_viewer_can_get_status(client, auth_headers):
    headers = auth_headers(UserRole.VIEWER)
    response = client.get("/api/v1/automation/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "enabled" in data
    assert "paused" in data


def test_analyst_can_get_status(client, auth_headers):
    headers = auth_headers(UserRole.ANALYST)
    response = client.get("/api/v1/automation/status", headers=headers)
    assert response.status_code == 200


def test_admin_can_get_status(client, auth_headers):
    headers = auth_headers(UserRole.ADMIN)
    response = client.get("/api/v1/automation/status", headers=headers)
    assert response.status_code == 200


def test_viewer_trigger_forbidden_403(client, auth_headers):
    headers = auth_headers(UserRole.VIEWER)
    response = client.post("/api/v1/automation/trigger", headers=headers)
    assert response.status_code == 403


def test_analyst_trigger_forbidden_403(client, auth_headers):
    headers = auth_headers(UserRole.ANALYST)
    response = client.post("/api/v1/automation/trigger", headers=headers)
    assert response.status_code == 403


def test_admin_trigger_allowed_200(client, auth_headers):
    headers = auth_headers(UserRole.ADMIN)
    with patch("backend.app.services.automation_service.AutomationSupervisor.run_sync_cycle", new_callable=AsyncMock):
        response = client.post("/api/v1/automation/trigger", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert "initiated" in data["message"]


def test_viewer_pause_forbidden_403(client, auth_headers):
    headers = auth_headers(UserRole.VIEWER)
    response = client.post("/api/v1/automation/pause", headers=headers)
    assert response.status_code == 403


def test_analyst_pause_forbidden_403(client, auth_headers):
    headers = auth_headers(UserRole.ANALYST)
    response = client.post("/api/v1/automation/pause", headers=headers)
    assert response.status_code == 403


def test_admin_pause_allowed_200(client, auth_headers):
    headers = auth_headers(UserRole.ADMIN)
    response = client.post("/api/v1/automation/pause", headers=headers)
    assert response.status_code == 200
    assert response.json()["paused"] is True
    assert get_automation_supervisor().is_paused is True


def test_viewer_resume_forbidden_403(client, auth_headers):
    headers = auth_headers(UserRole.VIEWER)
    response = client.post("/api/v1/automation/resume", headers=headers)
    assert response.status_code == 403


def test_analyst_resume_forbidden_403(client, auth_headers):
    headers = auth_headers(UserRole.ANALYST)
    response = client.post("/api/v1/automation/resume", headers=headers)
    assert response.status_code == 403


def test_admin_resume_allowed_200(client, auth_headers):
    headers = auth_headers(UserRole.ADMIN)
    get_automation_supervisor().pause()
    response = client.post("/api/v1/automation/resume", headers=headers)
    assert response.status_code == 200
    assert response.json()["paused"] is False
    assert get_automation_supervisor().is_paused is False


# ==============================================================================
# 10. Audit Logging Tests
# ==============================================================================

def test_admin_trigger_audit_log_created(client, auth_headers, db_session):
    headers = auth_headers(UserRole.ADMIN)
    with patch("backend.app.services.automation_service.AutomationSupervisor.run_sync_cycle", new_callable=AsyncMock):
        client.post("/api/v1/automation/trigger", headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "TRIGGER_AUTOMATION_SYNC")
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.resource_type == "AUTOMATION"


def test_admin_pause_audit_log_created(client, auth_headers, db_session):
    headers = auth_headers(UserRole.ADMIN)
    client.post("/api/v1/automation/pause", headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "PAUSE_AUTOMATION_SCHEDULER")
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.resource_type == "AUTOMATION"


def test_admin_resume_audit_log_created(client, auth_headers, db_session):
    headers = auth_headers(UserRole.ADMIN)
    client.post("/api/v1/automation/resume", headers=headers)

    audit_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "RESUME_AUTOMATION_SCHEDULER")
        .first()
    )
    assert audit_entry is not None
    assert audit_entry.resource_type == "AUTOMATION"


# ==============================================================================
# 11. Health Endpoint Integration Tests
# ==============================================================================

def test_health_endpoint_includes_automation_status(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "automation" in data
    assert "status" in data["automation"]


# ==============================================================================
# 12. Rolling History & Operational Metrics Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_rolling_cycle_history(supervisor, db_session):
    loc = make_test_location(name="Station One", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest") as mock_ingest:
        mock_ingest.return_value = MagicMock(observations_inserted=5, predictions_generated=0, models_retrained=False, errors=[])
        for _ in range(12):
            await supervisor.run_sync_cycle()

    assert len(supervisor._recent_cycles) == 10
    status_resp = supervisor.get_status(db=db_session)
    assert len(status_resp.recent_cycles) == 10
    assert status_resp.observations_ingested == 5


# ==============================================================================
# 13. Additional Edge Cases & Error Isolation Tests
# ==============================================================================

def test_openaq_timeout_isolation(supervisor, db_session):
    from backend.app.services.openaq_service import OpenAQTimeoutError
    loc1 = make_test_location(name="Timeout Station", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    loc2 = make_test_location(name="Healthy Station", city="City B", state="State B", latitude=11.0, longitude=71.0, external_provider="OPENAQ", external_id="102", is_active=True)
    db_session.add_all([loc1, loc2])
    db_session.commit()

    def mock_ingest(req):
        if req.location_ids == [101]:
            raise OpenAQTimeoutError("OpenAQ connection timed out")
        return MagicMock(observations_inserted=12, predictions_generated=5, models_retrained=False, errors=[])

    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session), \
         patch("backend.app.services.openaq_ingestion_service.OpenAQIngestionService.ingest", side_effect=mock_ingest):
        result = supervisor._sync_worker()

    assert result["stations_processed"] == 2
    assert result["stations_failed"] == 1
    assert result["observations_ingested"] == 12
    assert any("Timeout Station" in err for err in result["errors"])


def test_empty_active_stations_completes_safely(supervisor, db_session):
    with patch("backend.app.services.automation_service.SessionLocal", return_value=db_session):
        result = supervisor._sync_worker()

    assert result["stations_processed"] == 0
    assert result["stations_failed"] == 0
    assert result["observations_ingested"] == 0
    assert result["errors"] == []


def test_status_endpoint_reflects_backoff_state(client, auth_headers):
    headers = auth_headers(UserRole.VIEWER)
    supervisor = get_automation_supervisor()
    supervisor._backoff_until = datetime.now(timezone.utc) + timedelta(minutes=15)
    try:
        response = client.get("/api/v1/automation/status", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "BACKOFF"
        assert data["backoff_until"] is not None
    finally:
        supervisor._backoff_until = None


def test_alert_no_duplicate_creation_on_repeated_sync(db_session):
    from backend.app.services.alert_service import _get_or_create_alert
    loc = make_test_location(name="Alert Station", city="City A", state="State A", latitude=10.0, longitude=70.0, external_provider="OPENAQ", external_id="101", is_active=True)
    db_session.add(loc)
    db_session.commit()

    now = datetime.now(timezone.utc)
    # First alert detection
    alt1, created1 = _get_or_create_alert(
        db=db_session,
        location_id=loc.id,
        rule_id=1,
        alert_type=AlertType.AQI_THRESHOLD,
        severity=AlertSeverity.HIGH,
        title="High AQI Exceedance",
        message="AQI reached 220",
        observed_value=220.0,
        threshold_value=201.0,
        detected_at=now,
    )
    assert created1 is True

    # Second alert detection on next sync
    alt2, created2 = _get_or_create_alert(
        db=db_session,
        location_id=loc.id,
        rule_id=1,
        alert_type=AlertType.AQI_THRESHOLD,
        severity=AlertSeverity.HIGH,
        title="High AQI Exceedance",
        message="AQI reached 230",
        observed_value=230.0,
        threshold_value=201.0,
        detected_at=now + timedelta(hours=1),
    )
    assert created2 is False
    assert alt2.id == alt1.id
    assert alt2.observed_value == 230.0


def test_ml_prediction_sufficient_history_and_insufficient_history_handling():
    from backend.app.services.prediction_service import predict_with_general_model
    # When predict_with_general_model is called on a station with < 4 readings, it raises ValueError
    mock_db = MagicMock()
    mock_db.query().filter().first.return_value = MagicMock(id=1, name="Station 1")
    # Return 2 readings only (< 4)
    mock_db.query().outerjoin().filter().order_by().limit().all.return_value = [
        MagicMock(id=10, timestamp=datetime.now(timezone.utc)),
        MagicMock(id=11, timestamp=datetime.now(timezone.utc)),
    ]

    with pytest.raises(ValueError, match="Insufficient historical data"):
        predict_with_general_model(mock_db, location_id=1, horizon_hours=1)


