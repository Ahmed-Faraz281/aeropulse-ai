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
from backend.app.models.alert import AlertRule, AlertSeverity, AlertType
from backend.app.models.audit_log import AuditLog
from backend.app.models.system_setting import SettingCategory, SystemSetting

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
admin_user_id = 0
analyst_user_id = 0
viewer_user_id = 0


@pytest.fixture(autouse=True)
def setup_admin_test_db():
    global admin_token, analyst_token, viewer_token
    global admin_user_id, analyst_user_id, viewer_user_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # 1. Create standard users
    admin = User(
        username="admin_adm",
        email="admin_adm@aeropulse.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_adm",
        email="analyst_adm@aeropulse.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_adm",
        email="viewer_adm@aeropulse.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()
    db.refresh(admin)
    db.refresh(analyst)
    db.refresh(viewer)

    admin_user_id = admin.id
    analyst_user_id = analyst.id
    viewer_user_id = viewer.id

    # 2. Add sample locations and data sources for overview metrics
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
        latitude=28.6304,
        longitude=77.2177,
        is_active=False,
    )
    db.add_all([loc1, loc2])

    ds1 = DataSource(
        name="CPCB Public API Stream",
        source_type=SourceType.API,
        provider="CPCB",
        is_active=True,
    )
    ds2 = DataSource(
        name="Stochastic Simulation Feed",
        source_type=SourceType.SIMULATED,
        provider="AeroPulse Simulator",
        is_active=True,
    )
    db.add_all([ds1, ds2])

    rule1 = AlertRule(
        name="High AQI Exceedance",
        alert_type=AlertType.AQI_THRESHOLD,
        threshold=250.0,
        severity=AlertSeverity.HIGH,
        enabled=True,
    )
    db.add(rule1)

    # 3. Seed initial system settings
    s1 = SystemSetting(
        key="app_name",
        value="AeroPulse AI",
        value_type="string",
        category=SettingCategory.GENERAL,
        description="Application Display Name",
    )
    s2 = SystemSetting(
        key="ui_refresh_interval_seconds",
        value="30",
        value_type="int",
        category=SettingCategory.UI,
        description="Dashboard Polling Frequency",
    )
    s3 = SystemSetting(
        key="prediction_forecast_horizons_hours",
        value="[1, 3, 6, 12, 24]",
        value_type="json",
        category=SettingCategory.PREDICTION,
        description="Supported Prediction Forecast Horizons",
    )
    db.add_all([s1, s2, s3])
    db.commit()
    db.close()

    # Generate JWT Tokens
    r1 = client.post("/api/v1/auth/login", json={"username": "admin_adm", "password": "AdminPass123!"})
    admin_token = r1.json()["access_token"]

    r2 = client.post("/api/v1/auth/login", json={"username": "analyst_adm", "password": "AnalystPass123!"})
    analyst_token = r2.json()["access_token"]

    r3 = client.post("/api/v1/auth/login", json={"username": "viewer_adm", "password": "ViewerPass123!"})
    viewer_token = r3.json()["access_token"]

    yield
    app.dependency_overrides.clear()


# ==============================================================================
# Overview Tests
# ==============================================================================

def test_admin_overview_metrics():
    res = client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "users" in data
    assert data["users"]["total"] >= 3
    assert data["users"]["active"] >= 3
    assert data["users"]["inactive"] == 0
    assert data["users"]["by_role"]["admin"] >= 1
    assert data["locations"]["total"] == 2
    assert data["locations"]["active"] == 1
    assert data["locations"]["inactive"] == 1
    assert data["data_sources"]["total"] == 2
    assert data["data_sources"]["by_type"]["API"] == 1
    assert data["data_sources"]["by_type"]["SIMULATED"] == 1
    assert data["alert_rules"]["total"] == 1
    assert data["alert_rules"]["enabled"] == 1
    assert "system_status" in data
    assert data["system_status"]["database_connected"] is True


def test_admin_overview_rbac():
    # Unauthenticated
    r_unauth = client.get("/api/v1/admin/overview")
    assert r_unauth.status_code == 401

    # Viewer forbidden
    r_view = client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r_view.status_code == 403

    # Analyst forbidden
    r_analyst = client.get(
        "/api/v1/admin/overview",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r_analyst.status_code == 403


# ==============================================================================
# User Administration Tests
# ==============================================================================

def test_admin_list_users_paginated():
    res = client.get(
        "/api/v1/admin/users?page=1&page_size=2",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert data["total"] >= 3
    assert len(data["items"]) == 2
    # Ensure password hashes are never exposed
    for u in data["items"]:
        assert "password" not in u
        assert "password_hash" not in u


def test_admin_list_users_filters():
    # Search by username
    res = client.get(
        "/api/v1/admin/users?search=analyst_adm",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["username"] == "analyst_adm"

    # Filter by role
    res_role = client.get(
        "/api/v1/admin/users?role=viewer",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_role.status_code == 200
    assert all(u["role"] == "viewer" for u in res_role.json()["items"])


def test_admin_create_user_success():
    payload = {
        "username": "new_engineer",
        "email": "engineer@aeropulse.org",
        "password": "SecurePassword123!",
        "role": "analyst",
        "is_active": True,
    }
    res = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["username"] == "new_engineer"
    assert data["email"] == "engineer@aeropulse.org"
    assert data["role"] == "analyst"
    assert "password" not in data

    # Verify audit log was emitted
    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "USER_CREATED", AuditLog.resource_id == str(data["id"]))
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_adm"
    assert log.resource_type == "USER"
    assert "SecurePassword123!" not in str(log.new_value)
    db.close()


def test_admin_create_user_duplicate_username():
    payload = {
        "username": "admin_adm",
        "email": "another_admin@aeropulse.org",
        "password": "SecurePassword123!",
        "role": "admin",
        "is_active": True,
    }
    res = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"]


def test_admin_create_user_duplicate_email():
    payload = {
        "username": "brand_new_admin",
        "email": "admin_adm@aeropulse.org",
        "password": "SecurePassword123!",
        "role": "admin",
        "is_active": True,
    }
    res = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 409


def test_admin_create_user_invalid_role():
    payload = {
        "username": "hacker_user",
        "email": "hacker@aeropulse.org",
        "password": "SecurePassword123!",
        "role": "super_root_admin",
        "is_active": True,
    }
    res = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 422


def test_admin_create_user_rbac():
    payload = {
        "username": "analyst_create_attempt",
        "email": "attempt@aeropulse.org",
        "password": "SecurePassword123!",
        "role": "viewer",
    }
    res = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res.status_code == 403


def test_admin_update_user_role():
    res = client.put(
        f"/api/v1/admin/users/{analyst_user_id}",
        json={"role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"

    # Verify audit log
    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "USER_ROLE_CHANGED", AuditLog.resource_id == str(analyst_user_id))
        .first()
    )
    assert log is not None
    assert log.new_value["role"] == "viewer"
    db.close()


def test_admin_update_user_status():
    res = client.put(
        f"/api/v1/admin/users/{viewer_user_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False

    # Verify audit log
    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "USER_DEACTIVATED", AuditLog.resource_id == str(viewer_user_id))
        .first()
    )
    assert log is not None
    db.close()


def test_admin_update_user_self_deactivation_blocked():
    # Admin attempting to deactivate their own account
    res = client.put(
        f"/api/v1/admin/users/{admin_user_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 400
    assert "cannot deactivate or demote their own account" in res.json()["detail"].lower()


def test_admin_update_user_self_demotion_blocked():
    # Admin attempting to demote their own account to viewer
    res = client.put(
        f"/api/v1/admin/users/{admin_user_id}",
        json={"role": "viewer"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 400
    assert "cannot deactivate or demote their own account" in res.json()["detail"].lower()


def test_admin_update_user_last_admin_protection():
    # First create a second admin
    payload = {
        "username": "second_admin",
        "email": "admin2@aeropulse.org",
        "password": "Password123!",
        "role": "admin",
        "is_active": True,
    }
    r_create = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    admin2_id = r_create.json()["id"]

    # Now admin1 deactivates admin2 -> Allowed since admin1 is still active
    r_deact2 = client.put(
        f"/api/v1/admin/users/{admin2_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_deact2.status_code == 200

    # Now there is only 1 active admin (admin1).
    # If a script/user tries to demote admin1 or deactivate admin1 -> Last admin guard blocks it
    # Let's test with another admin token if admin2 was active, or directly test last active admin check:
    r_last = client.put(
        f"/api/v1/admin/users/{admin_user_id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_last.status_code == 400


def test_admin_update_user_nonexistent():
    res = client.put(
        "/api/v1/admin/users/99999",
        json={"role": "analyst"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 404


# ==============================================================================
# System Settings Tests
# ==============================================================================

def test_admin_system_settings_list():
    res = client.get(
        "/api/v1/admin/settings",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    settings = res.json()
    assert len(settings) >= 3
    keys = [s["key"] for s in settings]
    assert "app_name" in keys
    assert "ui_refresh_interval_seconds" in keys
    assert "prediction_forecast_horizons_hours" in keys


def test_admin_system_settings_update_success():
    res = client.put(
        "/api/v1/admin/settings/ui_refresh_interval_seconds",
        json={"value": "45"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["value"] == "45"

    # Audit log verification
    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "CONFIG_UPDATED", AuditLog.resource_id == "ui_refresh_interval_seconds")
        .first()
    )
    assert log is not None
    assert log.old_value["value"] == "30"
    assert log.new_value["value"] == "45"
    db.close()


def test_admin_system_settings_prediction_horizons_valid():
    # Valid subset of [1, 3, 6, 12, 24]
    res = client.put(
        "/api/v1/admin/settings/prediction_forecast_horizons_hours",
        json={"value": "[1, 6, 24]"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    assert res.json()["value"] == "[1, 6, 24]"


def test_admin_system_settings_prediction_horizons_invalid():
    # Attempting to add 48h which is not supported by Phase 9
    res = client.put(
        "/api/v1/admin/settings/prediction_forecast_horizons_hours",
        json={"value": "[1, 6, 24, 48]"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 400
    assert "unsupported horizon" in res.json()["detail"].lower()


def test_admin_system_settings_invalid_type_bounds():
    # Refresh interval < 5 seconds
    res = client.put(
        "/api/v1/admin/settings/ui_refresh_interval_seconds",
        json={"value": "2"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 400
    assert "at least 5 seconds" in res.json()["detail"].lower()

    # Non-integer value for int setting
    res_str = client.put(
        "/api/v1/admin/settings/ui_refresh_interval_seconds",
        json={"value": "not_a_number"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_str.status_code == 400


def test_admin_system_settings_nonexistent():
    res = client.put(
        "/api/v1/admin/settings/non_existent_key",
        json={"value": "foo"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 404


def test_admin_system_settings_rbac():
    # Viewer cannot update
    res_view = client.put(
        "/api/v1/admin/settings/ui_refresh_interval_seconds",
        json={"value": "60"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_view.status_code == 403

    # Analyst cannot update
    res_ana = client.put(
        "/api/v1/admin/settings/ui_refresh_interval_seconds",
        json={"value": "60"},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert res_ana.status_code == 403
