"""
Phase 15 — Security Hardening, Boundary Defense, Provenance & Reliability Test Suite.
Comprehensive regression and vulnerability testing across 8 core domains.
"""

from datetime import datetime, timedelta, timezone
import math
from typing import Optional
from jose import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.database import Base, get_db
from backend.app.core.security import create_access_token, get_password_hash
from backend.app.models.user import User, UserRole
from backend.app.models.location import Location
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import AlertRule, AlertSeverity, AlertType, Alert
from backend.app.models.audit_log import AuditLog
from backend.app.models.system_setting import SystemSetting, SettingCategory
from backend.app.schemas.air_quality import AirQualityReadingCreate
from backend.app.services.aqi_breakpoints import calculate_sub_index
from backend.app.services.aqi_engine import calculate_aqi, AQIStatus
from backend.app.services.data_validator import validate_reading_data
from backend.app.services.analytics import (
    calculate_summary_statistics,
    compute_trend_direction,
    aggregate_time_series,
    detect_anomalies,
)
from backend.app.services.admin_service import list_users_paginated
from backend.app.services.audit_service import query_audit_logs

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
inactive_user_token = ""
test_loc_id = 0
test_source_id = 0
test_sim_source_id = 0


@pytest.fixture(autouse=True)
def setup_hardening_test_db():
    global admin_token, analyst_token, viewer_token, inactive_user_token
    global test_loc_id, test_source_id, test_sim_source_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # 1. Users
    admin = User(
        username="admin_h15",
        email="admin_h15@aeropulse.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_h15",
        email="analyst_h15@aeropulse.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_h15",
        email="viewer_h15@aeropulse.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    inactive_user = User(
        username="inactive_h15",
        email="inactive_h15@aeropulse.org",
        password_hash=get_password_hash("InactivePass123!"),
        role=UserRole.VIEWER,
        is_active=False,
    )
    db.add_all([admin, analyst, viewer, inactive_user])
    db.commit()

    admin_token = create_access_token(admin.username)
    analyst_token = create_access_token(analyst.username)
    viewer_token = create_access_token(viewer.username)
    inactive_user_token = create_access_token(inactive_user.username)

    # 2. Location
    loc = Location(
        name="Hardening Test Station",
        city="Mumbai",
        state="Maharashtra",
        country="India",
        latitude=19.0760,
        longitude=72.8777,
        is_active=True,
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    test_loc_id = loc.id

    # 3. Data Sources (One API, One SIMULATED)
    ds_api = DataSource(
        name="Official CPCB API",
        source_type=SourceType.API,
        is_active=True,
    )
    ds_sim = DataSource(
        name="Simulation Engine Source",
        source_type=SourceType.SIMULATED,
        is_active=True,
    )
    db.add_all([ds_api, ds_sim])
    db.commit()
    db.refresh(ds_api)
    db.refresh(ds_sim)
    test_source_id = ds_api.id
    test_sim_source_id = ds_sim.id

    # 4. Base system settings
    s1 = SystemSetting(
        key="prediction_forecast_horizons_hours",
        value="[1, 3, 6, 12, 24]",
        value_type="json",
        category=SettingCategory.PREDICTION,
    )
    s2 = SystemSetting(
        key="ui_refresh_interval_seconds",
        value="30",
        value_type="int",
        category=SettingCategory.UI,
    )
    db.add_all([s1, s2])
    db.commit()

    db.close()
    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.pop(get_db, None)


# ==============================================================================
# Category 1: Authentication & Token Security (6 tests)
# ==============================================================================

def test_unauthenticated_request_rejected():
    """Unauthenticated request to protected route returns 401."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_malformed_token_rejected():
    """Garbled/malformed JWT token returns 401."""
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token-format"},
    )
    assert res.status_code == 401


def test_forged_signature_token_rejected():
    """Token signed with an unauthorized secret key returns 401."""
    payload = {
        "sub": "admin_h15",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    forged_token = jwt.encode(payload, "forged-unauthorized-key", algorithm=settings.ALGORITHM)
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {forged_token}"},
    )
    assert res.status_code == 401


def test_expired_token_rejected():
    """Expired JWT token returns 401."""
    payload = {
        "sub": "admin_h15",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=5),
    }
    expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401


def test_deactivated_account_login_rejected():
    """Deactivated user cannot log in and obtain access token."""
    res = client.post(
        "/api/v1/auth/login",
        json={"username": "inactive_h15", "password": "InactivePass123!"},
    )
    assert res.status_code == 400
    assert "Inactive" in res.json().get("detail", "")


def test_deactivated_user_token_access_rejected():
    """Token for deactivated user is rejected with HTTP 400 on protected routes."""
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {inactive_user_token}"},
    )
    assert res.status_code == 400
    assert "Inactive user account" in res.json().get("detail", "")


# ==============================================================================
# Category 2: RBAC Matrix Authorization (6 tests)
# ==============================================================================

def test_rbac_viewer_denied_admin_overview():
    """Viewer role is forbidden from admin endpoints."""
    res = client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 403


def test_rbac_viewer_denied_simulation_run():
    """Viewer role is forbidden from triggering simulation runs."""
    res = client.post(
        "/api/v1/simulation/run",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"location_id": test_loc_id, "scenario": "WINTER_SMOG"},
    )
    assert res.status_code == 403


def test_rbac_viewer_denied_model_training():
    """Viewer role is forbidden from initiating ML training."""
    res = client.post(
        "/api/v1/prediction/train",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"location_id": test_loc_id},
    )
    assert res.status_code == 403


def test_rbac_viewer_denied_reading_creation():
    """Viewer role is forbidden from ingesting air quality readings."""
    res = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pm25": 40.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert res.status_code == 403


def test_rbac_analyst_denied_admin_users():
    """Analyst role is forbidden from administering users."""
    res = client.post(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "username": "unauthorized_user",
            "email": "unauthorized@aeropulse.org",
            "password": "Password123!",
            "role": "viewer",
        },
    )
    assert res.status_code == 403


def test_rbac_admin_full_access():
    """Admin role possesses full operational access."""
    res = client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert "users" in res.json()


# ==============================================================================
# Category 3: Numeric Boundaries & Non-Finite Numbers (8 tests)
# ==============================================================================

def test_nan_concentration_subindex_rejected():
    """calculate_sub_index cleanly rejects NaN concentration without returning 500."""
    sub_idx, warning = calculate_sub_index("pm25", float("nan"))
    assert sub_idx is None
    assert warning is not None
    assert "physically invalid" in warning


def test_inf_concentration_subindex_rejected():
    """calculate_sub_index cleanly rejects Inf concentration."""
    sub_idx, warning = calculate_sub_index("pm25", float("inf"))
    assert sub_idx is None
    assert warning is not None
    assert "physically invalid" in warning


def test_negative_inf_concentration_subindex_rejected():
    """calculate_sub_index cleanly rejects -Inf concentration."""
    sub_idx, warning = calculate_sub_index("pm25", float("-inf"))
    assert sub_idx is None
    assert warning is not None


def test_nan_concentration_aqi_engine_invalid():
    """calculate_aqi classifies NaN concentration as INVALID_DATA."""
    result = calculate_aqi(pm25=float("nan"), pm10=50.0, no2=40.0)
    assert result.status == AQIStatus.INVALID_DATA
    assert result.aqi is None
    assert "Non-finite concentration" in result.message


def test_inf_concentration_aqi_engine_invalid():
    """calculate_aqi classifies Inf concentration as INVALID_DATA."""
    result = calculate_aqi(pm25=float("inf"), pm10=50.0, no2=40.0)
    assert result.status == AQIStatus.INVALID_DATA
    assert result.aqi is None
    assert "Non-finite concentration" in result.message


def test_nan_reading_validator_invalid():
    """validate_reading_data flags NaN pollutant values as QualityStatus.INVALID."""
    reading_dto = AirQualityReadingCreate(
        location_id=test_loc_id,
        timestamp=datetime.now(timezone.utc),
        pm25=float("nan"),
        pm10=50.0,
        source_id=test_source_id,
        source_type=SourceType.API,
    )
    status, note = validate_reading_data(reading_dto)
    assert status == QualityStatus.INVALID
    assert "Non-finite" in note


def test_nan_temperature_validator_invalid():
    """validate_reading_data flags NaN temperature as QualityStatus.INVALID."""
    reading_dto = AirQualityReadingCreate(
        location_id=test_loc_id,
        timestamp=datetime.now(timezone.utc),
        pm25=40.0,
        temperature=float("nan"),
        source_id=test_source_id,
        source_type=SourceType.API,
    )
    status, note = validate_reading_data(reading_dto)
    assert status == QualityStatus.INVALID
    assert "temperature" in note.lower()


def test_nan_humidity_validator_schema_rejected():
    """Schema rejects NaN humidity at input validation boundary."""
    with pytest.raises(Exception):
        AirQualityReadingCreate(
            location_id=test_loc_id,
            timestamp=datetime.now(timezone.utc),
            pm25=40.0,
            humidity=float("nan"),
            source_id=test_source_id,
            source_type=SourceType.API,
        )


def test_nan_summary_analytics_filtered():
    """calculate_summary_statistics filters NaN values without poisoning summary stats."""
    stats = calculate_summary_statistics([10.0, float("nan"), 20.0, None, 30.0])
    assert stats["count"] == 3
    assert stats["mean"] == 20.0
    assert stats["minimum"] == 10.0
    assert stats["maximum"] == 30.0


# ==============================================================================
# Category 4: Data Source Provenance Integrity (5 tests)
# ==============================================================================

def test_reading_source_type_matching_data_source_accepted():
    """Reading matching referenced data source source_type is accepted."""
    now = datetime.now(timezone.utc)
    res = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 42.0,
            "source_id": test_source_id,
            "source_type": "API",
        },
    )
    assert res.status_code == 201
    assert res.json()["source_type"] == "API"


def test_reading_source_type_mismatch_rejected():
    """Reading claiming source_type='API' for simulated source is rejected with 400."""
    now = datetime.now(timezone.utc)
    res = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 42.0,
            "source_id": test_sim_source_id,  # Registered as SIMULATED
            "source_type": "API",             # Falsely claimed as API
        },
    )
    assert res.status_code == 400
    assert "Provenance integrity violation" in res.json().get("detail", "")


def test_data_source_update_disallows_source_type_mutation():
    """PUT /api/v1/data-sources/{id} ignores or forbids mutating source_type."""
    res = client.put(
        f"/api/v1/data-sources/{test_source_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Updated Official API",
            "source_type": "SIMULATED",  # Malicious attempt to change immutable source_type
        },
    )
    assert res.status_code == 200
    # Provenance remains strictly API
    assert res.json()["source_type"] == "API"
    assert res.json()["name"] == "Updated Official API"


def test_data_source_audit_event_logged():
    """Data source mutations write an immutable audit record."""
    client.put(
        f"/api/v1/data-sources/{test_source_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Audited Official API"},
    )
    audit_res = client.get(
        "/api/v1/admin/audit-logs?resource_type=DATA_SOURCE",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit_res.status_code == 200
    logs = audit_res.json()["items"]
    assert any(l["action"] == "DATA_SOURCE_UPDATED" for l in logs)


def test_reading_invalid_data_source_id_rejected():
    """Ingesting reading referencing non-existent data source ID returns 404."""
    now = datetime.now(timezone.utc)
    res = client.post(
        "/api/v1/air-quality/readings",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "timestamp": now.isoformat(),
            "pm25": 30.0,
            "source_id": 999999,
            "source_type": "API",
        },
    )
    assert res.status_code == 404


# ==============================================================================
# Category 5: Time Window & Query Boundary Validation (5 tests)
# ==============================================================================

def test_historical_readings_inverted_window_rejected():
    """Historical readings query with start_time > end_time returns 422."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=2)
    res = client.get(
        "/api/v1/air-quality/history",
        params={"start_time": now.isoformat(), "end_time": past.isoformat()},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 422
    assert "Invalid time window" in res.json().get("detail", "")


def test_audit_logs_inverted_window_rejected():
    """Audit logs query with start_time > end_time returns 422."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=2)
    res = client.get(
        "/api/v1/admin/audit-logs",
        params={"start_time": now.isoformat(), "end_time": past.isoformat()},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 422
    assert "Invalid time window" in res.json().get("detail", "")


def test_analytics_inverted_window_rejected():
    """Analytics summary query with start_time > end_time returns 422."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=2)
    res = client.get(
        "/api/v1/analytics/summary",
        params={
            "location_id": test_loc_id,
            "start_time": now.isoformat(),
            "end_time": past.isoformat(),
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 422


def test_report_inverted_window_rejected():
    """Report preview with start_date > end_date returns 422."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=2)
    res = client.post(
        "/api/v1/reports/preview",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "report_type": "EXECUTIVE_SUMMARY",
            "location_id": test_loc_id,
            "start_date": now.isoformat(),
            "end_date": past.isoformat(),
        },
    )
    assert res.status_code == 422


def test_historical_readings_equal_start_end_accepted():
    """Historical readings query with start_time == end_time returns 200."""
    now = datetime.now(timezone.utc)
    res = client.get(
        "/api/v1/air-quality/history",
        params={"start_time": now.isoformat(), "end_time": now.isoformat()},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res.status_code == 200


# ==============================================================================
# Category 6: Pagination Boundaries & Negative Offsets (4 tests)
# ==============================================================================

def test_list_users_page_zero_safely_handled():
    """Requesting page=0 does not generate negative offset error."""
    db = TestingSessionLocal()
    users, total = list_users_paginated(db=db, page=0, page_size=10)
    db.close()
    assert total >= 4
    assert len(users) >= 4


def test_audit_logs_page_zero_safely_handled():
    """query_audit_logs with page=0 does not crash with negative SQL offset."""
    db = TestingSessionLocal()
    logs, total = query_audit_logs(db=db, page=0, page_size=10)
    db.close()
    assert isinstance(logs, list)


def test_list_users_oversized_page_size_clamped():
    """list_users_paginated clamps oversized page_size to 100."""
    db = TestingSessionLocal()
    users, total = list_users_paginated(db=db, page=1, page_size=1000)
    db.close()
    assert total >= 4
    assert len(users) <= 100


def test_list_users_page_beyond_total_results():
    """Requesting page 9999 returns empty items array with valid total count."""
    db = TestingSessionLocal()
    users, total = list_users_paginated(db=db, page=9999, page_size=10)
    db.close()
    assert total >= 4
    assert len(users) == 0


# ==============================================================================
# Category 7: What-If Simulation Edge Cases (5 tests)
# ==============================================================================

def test_what_if_zero_change_baseline_zero():
    """What-If simulation with baseline AQI 0 and 0 change gives aqi_percent_delta = 0.0."""
    db = TestingSessionLocal()
    # Ingest clean zero-reading
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=test_loc_id,
        timestamp=now,
        pm25=0.0,
        pm10=0.0,
        no2=0.0,
        source_id=test_source_id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading)
    db.commit()

    from backend.app.schemas.what_if import WhatIfSimulationRequest
    from backend.app.services.what_if_service import run_what_if_simulation

    request_payload = WhatIfSimulationRequest(
        location_id=test_loc_id,
        pollutant_changes={"pm25": 0.0, "pm10": 0.0},
    )
    result = run_what_if_simulation(db=db, request=request_payload)
    db.close()

    assert result.impact.aqi_delta == 0
    assert result.impact.aqi_percent_delta == 0.0
    assert result.impact.direction == "UNCHANGED"


def test_what_if_negative_100_percent_reduction():
    """What-If simulation with -100% reduction clamps concentrations to 0."""
    db = TestingSessionLocal()
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    reading = AirQualityReading(
        location_id=test_loc_id,
        timestamp=now,
        pm25=100.0,
        pm10=150.0,
        no2=80.0,
        source_id=test_source_id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading)
    db.commit()

    from backend.app.schemas.what_if import WhatIfSimulationRequest
    from backend.app.services.what_if_service import run_what_if_simulation

    request_payload = WhatIfSimulationRequest(
        location_id=test_loc_id,
        pollutant_changes={"pm25": -100.0, "pm10": -100.0, "no2": -100.0},
    )
    result = run_what_if_simulation(db=db, request=request_payload)
    db.close()

    assert result.scenario.simulated_aqi == 0
    assert result.scenario.category == "Good"


def test_what_if_exceed_500_percent_rejected():
    """What-If modifier exceeding +500% is rejected with 400."""
    db = TestingSessionLocal()
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=test_loc_id,
        timestamp=now,
        pm25=50.0,
        pm10=80.0,
        no2=30.0,
        source_id=test_source_id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading)
    db.commit()
    db.close()

    res = client.post(
        "/api/v1/what-if/simulate",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "pollutant_changes": {"pm25": 550.0},
        },
    )
    assert res.status_code == 400
    assert "must be between -100% and +500%" in res.json().get("detail", "")


def test_what_if_below_minus_100_percent_rejected():
    """What-If modifier below -100% is rejected with 400."""
    db = TestingSessionLocal()
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=test_loc_id,
        timestamp=now,
        pm25=50.0,
        pm10=80.0,
        no2=30.0,
        source_id=test_source_id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading)
    db.commit()
    db.close()

    res = client.post(
        "/api/v1/what-if/simulate",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "pollutant_changes": {"pm25": -120.0},
        },
    )
    assert res.status_code == 400
    assert "must be between -100% and +500%" in res.json().get("detail", "")


def test_what_if_stateless_no_db_records():
    """What-If simulation execution creates zero database reading and zero alert records."""
    db = TestingSessionLocal()
    now = datetime.now(timezone.utc)
    reading = AirQualityReading(
        location_id=test_loc_id,
        timestamp=now,
        pm25=55.0,
        pm10=95.0,
        no2=40.0,
        source_id=test_source_id,
        source_type=SourceType.API,
        quality_status=QualityStatus.VALID,
    )
    db.add(reading)
    db.commit()

    readings_before = db.query(AirQualityReading).count()
    alerts_before = db.query(Alert).count()
    db.close()

    res = client.post(
        "/api/v1/what-if/simulate",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "location_id": test_loc_id,
            "pollutant_changes": {"pm25": 50.0},
        },
    )
    assert res.status_code == 200

    db = TestingSessionLocal()
    readings_after = db.query(AirQualityReading).count()
    alerts_after = db.query(Alert).count()
    db.close()

    assert readings_after == readings_before
    assert alerts_after == alerts_before


# ==============================================================================
# Category 8: Audit Immutability & System Configuration (4 tests)
# ==============================================================================

def test_audit_logs_no_put_endpoint():
    """Audit logs are strictly immutable: PUT returns 405 Method Not Allowed."""
    res = client.put(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"notes": "tamper attempt"},
    )
    assert res.status_code == 405


def test_audit_logs_no_delete_endpoint():
    """Audit logs cannot be deleted: DELETE returns 404 or 405."""
    res = client.delete(
        "/api/v1/admin/audit-logs/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code in [404, 405]


def test_system_settings_invalid_horizons_rejected():
    """System settings reject prediction horizons outside [1, 3, 6, 12, 24]."""
    res = client.put(
        "/api/v1/admin/settings/prediction_forecast_horizons_hours",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"value": "[1, 3, 48]"},  # 48 is not supported in Phase 9
    )
    assert res.status_code == 400
    assert "Unsupported horizon" in res.json().get("detail", "")


def test_system_settings_invalid_refresh_rejected():
    """System settings reject UI refresh intervals below 5 seconds."""
    res = client.put(
        "/api/v1/admin/settings/ui_refresh_interval_seconds",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"value": "2"},
    )
    assert res.status_code == 400
    assert "must be at least 5 seconds" in res.json().get("detail", "")
