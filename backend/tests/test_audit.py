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
from backend.app.models.alert import AlertRule, AlertSeverity, AlertType
from backend.app.models.audit_log import AuditLog
from backend.app.services.audit_service import sanitize_audit_dict

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


@pytest.fixture(autouse=True)
def setup_audit_test_db():
    global admin_token, analyst_token, viewer_token

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    admin = User(
        username="admin_aud",
        email="admin_aud@aeropulse.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_aud",
        email="analyst_aud@aeropulse.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_aud",
        email="viewer_aud@aeropulse.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Pre-seed sample audit logs for query testing
    t0 = datetime.now(timezone.utc) - timedelta(hours=2)
    t1 = datetime.now(timezone.utc) - timedelta(hours=1)
    log1 = AuditLog(
        timestamp=t0,
        username_snapshot="admin_aud",
        action="CONFIG_UPDATED",
        resource_type="SYSTEM_SETTING",
        resource_id="app_name",
        description="Updated system name",
        success=True,
    )
    log2 = AuditLog(
        timestamp=t1,
        username_snapshot="admin_aud",
        action="USER_CREATED",
        resource_type="USER",
        resource_id="10",
        description="Created analyst account",
        success=True,
    )
    db.add_all([log1, log2])
    db.commit()
    db.close()

    r1 = client.post("/api/v1/auth/login", json={"username": "admin_aud", "password": "AdminPass123!"})
    admin_token = r1.json()["access_token"]

    r2 = client.post("/api/v1/auth/login", json={"username": "analyst_aud", "password": "AnalystPass123!"})
    analyst_token = r2.json()["access_token"]

    r3 = client.post("/api/v1/auth/login", json={"username": "viewer_aud", "password": "ViewerPass123!"})
    viewer_token = r3.json()["access_token"]

    yield
    app.dependency_overrides.clear()


# ==============================================================================
# Audit Query & RBAC Tests
# ==============================================================================

def test_audit_log_query_paginated():
    res = client.get(
        "/api/v1/admin/audit-logs?page=1&page_size=10",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert data["total"] >= 2
    # Verify newest first order
    assert data["items"][0]["action"] == "USER_CREATED"
    assert data["items"][1]["action"] == "CONFIG_UPDATED"


def test_audit_log_filters():
    # Filter by action
    res_action = client.get(
        "/api/v1/admin/audit-logs?action=CONFIG_UPDATED",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_action.status_code == 200
    items = res_action.json()["items"]
    assert len(items) == 1
    assert items[0]["resource_id"] == "app_name"

    # Filter by resource_type
    res_type = client.get(
        "/api/v1/admin/audit-logs?resource_type=USER",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_type.status_code == 200
    assert all(i["resource_type"] == "USER" for i in res_type.json()["items"])


def test_audit_log_rbac():
    # Unauthenticated
    r_unauth = client.get("/api/v1/admin/audit-logs")
    assert r_unauth.status_code == 401

    # Viewer forbidden
    r_view = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r_view.status_code == 403

    # Analyst forbidden
    r_ana = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r_ana.status_code == 403


def test_audit_log_immutability():
    # Attempting PUT on audit-logs endpoint returns 404 or 405
    r_put = client.put(
        "/api/v1/admin/audit-logs/1",
        json={"description": "Tampered description"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_put.status_code in [404, 405]

    # Attempting DELETE on audit-logs endpoint returns 404 or 405
    r_del = client.delete(
        "/api/v1/admin/audit-logs/1",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_del.status_code in [404, 405]


def test_audit_log_secret_redaction():
    raw_dict = {
        "username": "alice",
        "password": "SuperSecretPassword!",
        "password_hash": "$2b$12$e5sdfsdf...",
        "token": "eyJhbGciOi...",
        "api_key": "sec_123456789",
        "nested": {
            "credentials": "db_user:password",
            "safe_field": "public_data",
        },
    }
    sanitized = sanitize_audit_dict(raw_dict)
    assert sanitized["username"] == "alice"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["password_hash"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["credentials"] == "[REDACTED]"
    assert sanitized["nested"]["safe_field"] == "public_data"


def test_audit_log_client_ip_resolution():
    # Admin creates user -> verify IP address recorded matches testclient
    payload = {
        "username": "ip_test_user",
        "email": "ip@aeropulse.org",
        "password": "Password123!",
        "role": "viewer",
    }
    res = client.post(
        "/api/v1/admin/users",
        json=payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 201

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "USER_CREATED", AuditLog.username_snapshot == "admin_aud")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.ip_address in ["testclient", "127.0.0.1", None]
    db.close()


# ==============================================================================
# Domain Routers Audit Hooks Tests
# ==============================================================================

def test_audit_hook_location_created():
    loc_payload = {
        "name": "BTM Layout Station",
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
        "latitude": 12.9166,
        "longitude": 77.6101,
    }
    res = client.post(
        "/api/v1/locations",
        json=loc_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 201
    loc_id = res.json()["id"]

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "LOCATION_CREATED", AuditLog.resource_id == str(loc_id))
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_aud"
    assert log.resource_type == "LOCATION"
    assert log.new_value["name"] == "BTM Layout Station"
    db.close()


def test_audit_hook_location_updated():
    # Setup location
    loc_payload = {
        "name": "Whitefield Hub",
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
        "latitude": 12.9698,
        "longitude": 77.7500,
    }
    res_c = client.post(
        "/api/v1/locations",
        json=loc_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    loc_id = res_c.json()["id"]

    # Update location
    res_u = client.put(
        f"/api/v1/locations/{loc_id}",
        json={"description": "Updated Whitefield Sensor Array", "is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_u.status_code == 200

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.resource_id == str(loc_id),
            AuditLog.action.in_(["LOCATION_UPDATED", "LOCATION_DEACTIVATED"]),
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_aud"
    assert log.new_value["is_active"] is False
    db.close()


def test_audit_hook_data_source_created():
    ds_payload = {
        "name": "State Pollution Board Feed",
        "source_type": "API",
        "provider": "KSPCB",
        "description": "Continuous telemetry",
    }
    res = client.post(
        "/api/v1/data-sources",
        json=ds_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 201
    ds_id = res.json()["id"]

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DATA_SOURCE_CREATED", AuditLog.resource_id == str(ds_id))
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_aud"
    assert log.resource_type == "DATA_SOURCE"
    assert log.new_value["source_type"] == "API"
    db.close()


def test_audit_hook_data_source_updated():
    # Setup data source
    ds_payload = {
        "name": "Simulated Research Stream",
        "source_type": "SIMULATED",
        "provider": "AeroPulse Lab",
    }
    res_c = client.post(
        "/api/v1/data-sources",
        json=ds_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ds_id = res_c.json()["id"]

    # Update data source description and active status
    res_u = client.put(
        f"/api/v1/data-sources/{ds_id}",
        json={"name": "Simulated Research Stream v2", "is_active": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_u.status_code == 200
    assert res_u.json()["name"] == "Simulated Research Stream v2"
    assert res_u.json()["is_active"] is False
    # Ensure source_type is strictly preserved
    assert res_u.json()["source_type"] == "SIMULATED"

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.resource_id == str(ds_id), AuditLog.resource_type == "DATA_SOURCE")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_aud"
    assert log.new_value["is_active"] is False
    db.close()


def test_data_source_provenance_immutability():
    # Verify that attempting to change source_type from SIMULATED to API is ignored or blocked
    ds_payload = {
        "name": "Synthetic Sensor Stream",
        "source_type": "SIMULATED",
    }
    res_c = client.post(
        "/api/v1/data-sources",
        json=ds_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    ds_id = res_c.json()["id"]

    # Attempt to send source_type: "API" in PUT request
    res_u = client.put(
        f"/api/v1/data-sources/{ds_id}",
        json={"source_type": "API", "name": "Altered Source"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_u.status_code == 200
    # Provenance must remain SIMULATED
    assert res_u.json()["source_type"] == "SIMULATED"


def test_audit_hook_alert_rule_created():
    rule_payload = {
        "name": "Severe Smog Threshold",
        "alert_type": "AQI_THRESHOLD",
        "threshold": 350.0,
        "severity": "CRITICAL",
        "enabled": True,
    }
    res = client.post(
        "/api/v1/alerts/rules",
        json=rule_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 201
    rule_id = res.json()["id"]

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "ALERT_RULE_CREATED", AuditLog.resource_id == str(rule_id))
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_aud"
    assert log.resource_type == "ALERT_RULE"
    assert log.new_value["threshold"] == 350.0
    db.close()


def test_audit_hook_alert_rule_updated():
    rule_payload = {
        "name": "Moderate AQI Alert",
        "alert_type": "AQI_THRESHOLD",
        "threshold": 100.0,
        "severity": "WARNING",
        "enabled": True,
    }
    res_c = client.post(
        "/api/v1/alerts/rules",
        json=rule_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = res_c.json()["id"]

    # Disable rule
    res_u = client.put(
        f"/api/v1/alerts/rules/{rule_id}",
        json={"enabled": False, "threshold": 120.0},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_u.status_code == 200
    assert res_u.json()["enabled"] is False

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.resource_id == str(rule_id),
            AuditLog.action.in_(["ALERT_RULE_UPDATED", "ALERT_RULE_DISABLED"]),
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.new_value["enabled"] is False
    db.close()


def test_audit_hook_alert_rule_deleted():
    rule_payload = {
        "name": "Temporary Test Rule",
        "alert_type": "AQI_THRESHOLD",
        "threshold": 99.0,
        "severity": "INFO",
        "enabled": True,
    }
    res_c = client.post(
        "/api/v1/alerts/rules",
        json=rule_payload,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    rule_id = res_c.json()["id"]

    # Delete rule
    res_d = client.delete(
        f"/api/v1/alerts/rules/{rule_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_d.status_code == 204

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "ALERT_RULE_DELETED", AuditLog.resource_id == str(rule_id))
        .first()
    )
    assert log is not None
    assert log.username_snapshot == "admin_aud"
    db.close()


def test_atomic_audit_rollback_on_failure():
    # If a mutation fails validation (e.g. invalid latitude on location), no audit log is persisted
    invalid_loc = {
        "name": "Invalid Station",
        "city": "Bengaluru",
        "state": "Karnataka",
        "latitude": 999.0,  # Invalid latitude (> 90)
        "longitude": 77.0,
    }
    res = client.post(
        "/api/v1/locations",
        json=invalid_loc,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 422

    db = TestingSessionLocal()
    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "LOCATION_CREATED", AuditLog.description.contains("Invalid Station"))
        .first()
    )
    assert log is None  # No orphan audit record
    db.close()
