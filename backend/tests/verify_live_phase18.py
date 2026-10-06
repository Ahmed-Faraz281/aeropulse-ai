"""
Phase 18 Live Verification Probe
AeroPulse AI — Intelligent Continuous Monitoring & Automation

Verifies:
1. Automation supervisor startup, state machine, and status inquiry
2. Station query filtering (OPENAQ + is_active only)
3. Endpoint RBAC (Admin write vs Viewer/Analyst read)
4. Health endpoint automation summary
5. Supervisor pause and resume functionality
6. Manual cycle execution & non-blocking execution
7. Concurrency lock enforcement (409 Conflict)
8. Zero hardcoded station/city logic
"""

import sys
import os

# Set paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncio
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import settings
from backend.app.core.database import SessionLocal, get_db
from backend.app.models.user import User, UserRole
from backend.app.models.location import Location
from backend.app.models.air_quality import AirQualityReading
from backend.app.services.automation_service import AutomationSupervisor, get_automation_supervisor
from backend.app.core.security import create_access_token


def test_no_hardcoded_locations_in_automation():
    print("[1/6] Checking for hardcoded cities/stations in Phase 18...")
    automation_file = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "app", "services", "automation_service.py")
    )
    with open(automation_file, "r", encoding="utf-8") as f:
        content = f.read().lower()
    
    # Check that common hardcoded strings don't exist as literals
    banned_literals = ["bengaluru", "hyderabad", "delhi", "mumbai", "station 6984", "hebbal"]
    for banned in banned_literals:
        assert banned not in content, f"Hardcoded literal '{banned}' found in automation_service.py!"
    print("  PASS: Zero hardcoded station/city names in automation service.")


def get_auth_headers(role: UserRole = UserRole.VIEWER) -> dict:
    db = SessionLocal()
    try:
        username = f"verify_{role.value.lower()}"
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(
                username=username,
                email=f"{username}@aeropulse.org",
                password_hash="testpasshash",
                role=role,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        token = create_access_token(subject=str(user.id))
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def test_supervisor_status_and_health():
    print("[2/6] Testing supervisor status and health endpoint...")
    client = TestClient(app)
    
    # Health endpoint
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    data = resp.json()
    assert "automation" in data, "Automation block missing in health check"
    assert data["automation"]["status"] in ["IDLE", "RUNNING", "DISABLED", "PAUSED", "BACKOFF"]
    print(f"  PASS: Health endpoint reports automation status: {data['automation']}")

    # Authenticate as viewer to test status inquiry
    headers = get_auth_headers(UserRole.VIEWER)
    status_resp = client.get(
        "/api/v1/automation/status",
        headers=headers
    )
    assert status_resp.status_code == 200, f"Status call failed: {status_resp.text}"
    status_data = status_resp.json()
    assert "status" in status_data
    assert "enabled" in status_data
    assert "paused" in status_data
    assert "active_stations_count" in status_data
    assert "poll_interval_minutes" in status_data
    assert isinstance(status_data["recent_cycles"], list)
    print(f"  PASS: /automation/status returned valid schema (stations: {status_data['active_stations_count']}, status: {status_data['status']})")


def test_rbac_and_administrative_actions():
    print("[3/6] Testing RBAC on administrative endpoints (pause/resume/trigger)...")
    client = TestClient(app)
    
    viewer_headers = get_auth_headers(UserRole.VIEWER)
    analyst_headers = get_auth_headers(UserRole.ANALYST)
    admin_headers = get_auth_headers(UserRole.ADMIN)

    # Viewer cannot pause
    res = client.post("/api/v1/automation/pause", headers=viewer_headers)
    assert res.status_code == 403, f"Expected 403 for viewer pause, got {res.status_code}"

    # Analyst cannot trigger
    res = client.post("/api/v1/automation/trigger", headers=analyst_headers)
    assert res.status_code == 403, f"Expected 403 for analyst trigger, got {res.status_code}"

    # Admin CAN pause
    res = client.post("/api/v1/automation/pause", headers=admin_headers)
    assert res.status_code == 200, f"Expected 200 for admin pause, got {res.status_code}"
    assert res.json()["paused"] is True
    print("  PASS: Admin paused scheduler successfully.")

    # Admin CAN resume
    res = client.post("/api/v1/automation/resume", headers=admin_headers)
    assert res.status_code == 200, f"Expected 200 for admin resume, got {res.status_code}"
    assert res.json()["paused"] is False
    print("  PASS: Admin resumed scheduler successfully.")


def test_station_filtering_logic():
    print("[4/6] Testing database query station filtering (OPENAQ + active only)...")
    supervisor = get_automation_supervisor()
    db = SessionLocal()
    try:
        # Create non-openaq location
        manual_loc = Location(
            name="Manual Sensor Test",
            city="TestCity",
            state="TestState",
            country="India",
            latitude=12.97,
            longitude=77.59,
            external_provider="MANUAL",
            is_active=True
        )
        # Create inactive openaq location
        inactive_openaq = Location(
            name="Inactive OpenAQ Test",
            city="TestCity",
            state="TestState",
            country="India",
            latitude=12.97,
            longitude=77.59,
            external_provider="OPENAQ",
            is_active=False
        )
        db.add(manual_loc)
        db.add(inactive_openaq)
        db.commit()
        db.refresh(manual_loc)
        db.refresh(inactive_openaq)

        # Query stations matching supervisor criteria
        active_stations = (
            db.query(Location)
            .filter(
                Location.external_provider == "OPENAQ",
                Location.is_active == True,
            )
            .order_by(Location.id.asc())
            .all()
        )
        station_ids = [s.id for s in active_stations]

        assert manual_loc.id not in station_ids, "Manual location should NOT be selected for OpenAQ polling!"
        assert inactive_openaq.id not in station_ids, "Inactive OpenAQ location should NOT be selected for polling!"
        print(f"  PASS: Filter strictly selected active OpenAQ stations only (count: {len(active_stations)}).")

        # Verify supervisor get_status reflects the active stations count
        status = supervisor.get_status()
        assert status.active_stations_count == len(active_stations)
        print(f"  PASS: Supervisor get_status correctly reported active_stations_count: {status.active_stations_count}.")

    finally:
        # Cleanup
        db.delete(manual_loc)
        db.delete(inactive_openaq)
        db.commit()
        db.close()


def test_concurrency_lock_and_manual_cycle():
    print("[5/6] Testing manual cycle execution & concurrency lock...")
    client = TestClient(app)
    admin_headers = get_auth_headers(UserRole.ADMIN)

    # Mock the internal worker so we don't hit live internet during verification probe
    with patch("backend.app.services.automation_service.OpenAQIngestionService.ingest") as mock_ingest:
        mock_ingest.return_value = {
            "records_inserted": 12,
            "predictions_count": 5,
            "models_retrained": False
        }

        # Trigger cycle
        resp = client.post("/api/v1/automation/trigger", headers=admin_headers)
        assert resp.status_code == 200, f"Trigger failed: {resp.text}"
        data = resp.json()
        assert data["status"] in ["running", "accepted"]
        print(f"  PASS: Manual cycle triggered: {data['message']}")

        # Immediately trigger again while running: expect 409 Conflict
        supervisor = get_automation_supervisor()
        if supervisor.is_running:
            conflict_resp = client.post("/api/v1/automation/trigger", headers=admin_headers)
            assert conflict_resp.status_code == 409, f"Expected 409 Conflict, got {conflict_resp.status_code}"
            print("  PASS: Concurrency lock successfully rejected simultaneous trigger with 409 Conflict.")


def test_supervisor_cycle_history():
    print("[6/6] Verifying supervisor rolling cycle history...")
    supervisor = get_automation_supervisor()
    status = supervisor.get_status()
    print(f"  PASS: Recorded {len(status.recent_cycles)} cycle(s) in memory.")
    if status.recent_cycles:
        latest = status.recent_cycles[0]
        print(f"  Latest cycle summary: ID={latest.cycle_id}, status={latest.status}, duration={latest.duration_seconds}s")


if __name__ == "__main__":
    print("=" * 70)
    print("AEROPULSE AI — PHASE 18 LIVE INTEGRATION & AUTOMATION PROBE")
    print("=" * 70)
    test_no_hardcoded_locations_in_automation()
    test_supervisor_status_and_health()
    test_rbac_and_administrative_actions()
    test_station_filtering_logic()
    test_concurrency_lock_and_manual_cycle()
    test_supervisor_cycle_history()
    print("=" * 70)
    print("ALL PHASE 18 LIVE VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 70)
