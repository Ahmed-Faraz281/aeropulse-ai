from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, UserRole
from backend.app.schemas.openaq import (
    OpenAQLocationNormalized,
    OpenAQSensorHoursResponse,
    OpenAQSensorNormalized,
)
from backend.app.services.openaq_service import (
    OpenAQAuthError,
    OpenAQConfigError,
    OpenAQNotFoundError,
    OpenAQRatelimitError,
    OpenAQService,
    OpenAQTimeoutError,
    OpenAQUpstreamError,
    OpenAQValidationError,
    get_openaq_service,
)

# In-memory test DB for auth fixtures
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
def setup_openaq_test_db():
    global admin_token, analyst_token, viewer_token

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    admin = User(
        username="admin_openaq",
        email="admin_openaq@aeropulse.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_openaq",
        email="analyst_openaq@aeropulse.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_openaq",
        email="viewer_openaq@aeropulse.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()
    db.close()

    r1 = client.post("/api/v1/auth/login", json={"username": "admin_openaq", "password": "AdminPass123!"})
    admin_token = r1.json()["access_token"]

    r2 = client.post("/api/v1/auth/login", json={"username": "analyst_openaq", "password": "AnalystPass123!"})
    analyst_token = r2.json()["access_token"]

    r3 = client.post("/api/v1/auth/login", json={"username": "viewer_openaq", "password": "ViewerPass123!"})
    viewer_token = r3.json()["access_token"]

    yield

    app.dependency_overrides.pop(get_openaq_service, None)
    Base.metadata.drop_all(bind=test_engine)


# Sample Mock Payloads
SAMPLE_LOCATION_RAW = {
    "id": 6984,
    "name": "Hebbal, Bengaluru - KSPCB",
    "locality": "Bengaluru",
    "timezone": "Asia/Kolkata",
    "country": {"code": "IN", "name": "India"},
    "owner": {"name": "CPCB"},
    "provider": {"name": "CPCB"},
    "coordinates": {"latitude": 13.029152, "longitude": 77.585901},
    "isMobile": False,
    "isMonitor": True,
    "instruments": [{"name": "Beta Attenuation Monitor"}],
    "sensors": [
        {
            "id": 12235249,
            "name": "Hebbal, Bengaluru - KSPCB pm25",
            "parameter": {"id": 2, "name": "pm25", "units": "µg/m³", "displayName": "PM2.5"},
        }
    ],
    "datetimeFirst": {"utc": "2024-01-01T00:00:00Z"},
    "datetimeLast": {"utc": "2024-05-01T00:00:00Z"},
}

SAMPLE_SENSOR_RAW_PM25 = {
    "id": 12235249,
    "name": "Hebbal pm25",
    "parameter": {"id": 2, "name": "pm25", "units": "µg/m³", "displayName": "PM2.5"},
    "datetimeFirst": {"utc": "2024-01-01T00:00:00Z"},
    "datetimeLast": {"utc": datetime.now(timezone.utc).isoformat()},
    "coverage": {
        "expectedCount": 100,
        "observedCount": 98,
        "percentComplete": 98.0,
        "percentCoverage": 98.0,
        "observedInterval": "1 hour",
    },
    "summary": {"min": 12.0, "max": 85.0, "avg": 38.4},
}

SAMPLE_SENSOR_RAW_TEMP = {
    "id": 12235250,
    "name": "Hebbal temperature",
    "parameter": {"id": 5, "name": "temperature", "units": "°C", "displayName": "Temperature"},
    "datetimeFirst": {"utc": "2024-01-01T00:00:00Z"},
    "datetimeLast": {"utc": "2024-05-01T00:00:00Z"},
    "coverage": None,
    "summary": {"min": 20.0, "max": 35.0, "avg": 27.2},
}


# ==============================================================================
# TEST 1: Missing API Key raises OpenAQConfigError & endpoint returns 503
# ==============================================================================
def test_openaq_missing_api_key_raises_config_error():
    service = OpenAQService(api_key="")
    with pytest.raises(OpenAQConfigError) as exc_info:
        service.get_location(6984)
    assert "OpenAQ API key is not configured" in str(exc_info.value)

    # Test HTTP 503 mapping via endpoint
    app.dependency_overrides[get_openaq_service] = lambda: OpenAQService(api_key="")
    response = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 503
    assert "OpenAQ API key is not configured" in response.json()["detail"]


# ==============================================================================
# TEST 2: Successful location fetch & normalization
# ==============================================================================
def test_openaq_get_location_success():
    mock_resp = httpx.Response(
        status_code=200,
        json={"results": [SAMPLE_LOCATION_RAW]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/6984"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    loc = service.get_location(6984)

    assert loc.id == 6984
    assert loc.name == "Hebbal, Bengaluru - KSPCB"
    assert loc.locality == "Bengaluru"
    assert loc.latitude == 13.029152
    assert loc.longitude == 77.585901
    assert loc.country_code == "IN"
    assert loc.instruments == ["Beta Attenuation Monitor"]
    assert len(loc.sensors) == 1
    assert loc.sensors[0].parameter_name == "pm25"
    assert loc.sensors[0].units == "µg/m³"

    # API endpoint test
    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 6984
    assert data["name"] == "Hebbal, Bengaluru - KSPCB"


# ==============================================================================
# TEST 3: Location Not Found raises OpenAQNotFoundError & endpoint returns 404
# ==============================================================================
def test_openaq_get_location_not_found():
    mock_resp = httpx.Response(
        status_code=404,
        json={"detail": "Not found"},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/999999"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    with pytest.raises(OpenAQNotFoundError):
        service.get_location(999999)

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations/999999",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 404


# ==============================================================================
# TEST 4: Search locations with valid radius returns normalized list
# ==============================================================================
def test_openaq_search_locations_with_valid_radius():
    mock_resp = httpx.Response(
        status_code=200,
        json={"results": [SAMPLE_LOCATION_RAW]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    app.dependency_overrides[get_openaq_service] = lambda: service

    response = client.get(
        "/api/v1/openaq/locations",
        params={"coordinates": "13.029,77.585", "radius": 10000},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 1
    assert len(data["locations"]) == 1
    assert data["locations"][0]["id"] == 6984


# ==============================================================================
# TEST 5: Search locations rejects negative radius (HTTP 422, no clamping)
# ==============================================================================
def test_openaq_search_locations_rejects_negative_radius():
    service = OpenAQService(api_key="valid-key")
    with pytest.raises(OpenAQValidationError) as exc_info:
        service.search_locations(radius=-100)
    assert "between 0 and 25,000 meters" in str(exc_info.value)

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations",
        params={"radius": -100},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 422


# ==============================================================================
# TEST 6: Search locations rejects excessive radius (>25,000m HTTP 422)
# ==============================================================================
def test_openaq_search_locations_rejects_excessive_radius():
    service = OpenAQService(api_key="valid-key")
    with pytest.raises(OpenAQValidationError) as exc_info:
        service.search_locations(radius=30000)
    assert "between 0 and 25,000 meters" in str(exc_info.value)

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations",
        params={"radius": 30000},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 422


# ==============================================================================
# TEST 7: Search locations rejects malformed or out-of-bounds coordinates
# ==============================================================================
def test_openaq_search_locations_rejects_malformed_coordinates():
    service = OpenAQService(api_key="valid-key")
    # Non-pair format
    with pytest.raises(OpenAQValidationError):
        service.search_locations(coordinates="invalid_coords")

    # Latitude out of bounds (> 90)
    with pytest.raises(OpenAQValidationError):
        service.search_locations(coordinates="95.0,77.5")

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations",
        params={"coordinates": "invalid"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 422


# ==============================================================================
# TEST 8: Sensor normalization handles both pollutants and environmental params
# ==============================================================================
def test_openaq_get_location_sensors_normalizes_pollutants_and_meteo():
    mock_resp = httpx.Response(
        status_code=200,
        json={"results": [SAMPLE_SENSOR_RAW_PM25, SAMPLE_SENSOR_RAW_TEMP]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/6984/sensors"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    sensors = service.get_location_sensors(6984)

    assert len(sensors) == 2
    # Pollutant
    assert sensors[0].parameter_name == "pm25"
    assert sensors[0].units == "µg/m³"
    # Environmental / meteorological parameter
    assert sensors[1].parameter_name == "temperature"
    assert sensors[1].units == "°C"

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations/6984/sensors",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 2
    assert data["sensors"][0]["parameter_name"] == "pm25"
    assert data["sensors"][1]["parameter_name"] == "temperature"


# ==============================================================================
# TEST 9: Sensor is_active defaults to None when unsupported by upstream
# ==============================================================================
def test_openaq_sensor_is_active_none_when_unsupported():
    raw_no_dates = {
        "id": 991,
        "name": "sensor_without_dates",
        "parameter": {"name": "co", "units": "ppm"},
        "datetimeFirst": None,
        "datetimeLast": None,
    }
    mock_resp = httpx.Response(
        status_code=200,
        json={"results": [raw_no_dates]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/sensors/991"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    sensor = service.get_sensor(991)
    # Must be None, not assumed True or False
    assert sensor.is_active is None

    # When datetimeLast is recent (< 7 days), is_active is True
    recent_raw = {
        "id": 992,
        "name": "recent_sensor",
        "parameter": {"name": "pm25", "units": "µg/m³"},
        "datetimeLast": {"utc": datetime.now(timezone.utc).isoformat()},
    }
    mock_resp_recent = httpx.Response(
        status_code=200,
        json={"results": [recent_raw]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/sensors/992"),
    )
    mock_client.request.return_value = mock_resp_recent
    recent_sensor = service.get_sensor(992)
    assert recent_sensor.is_active is True


# ==============================================================================
# TEST 10: Default factory ensures independent empty lists for sensors
# ==============================================================================
def test_openaq_sensor_default_factory_empty_list():
    loc1 = OpenAQLocationNormalized(id=1, name="Station 1")
    loc2 = OpenAQLocationNormalized(id=2, name="Station 2")

    assert loc1.sensors == []
    assert loc2.sensors == []
    # Verify default_factory produces separate list objects
    assert loc1.sensors is not loc2.sensors


# ==============================================================================
# TEST 11: Sensor hourly measurements fetch & normalization
# ==============================================================================
def test_openaq_get_sensor_hours_success():
    mock_meta_resp = httpx.Response(
        status_code=200,
        json={"results": [SAMPLE_SENSOR_RAW_PM25]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/sensors/12235249"),
    )
    mock_hours_resp = httpx.Response(
        status_code=200,
        json={
            "results": [
                {
                    "period": {
                        "datetimeFrom": {"utc": "2024-05-01T10:00:00Z", "local": "2024-05-01T15:30:00+05:30"},
                        "datetimeTo": {"utc": "2024-05-01T11:00:00Z", "local": "2024-05-01T16:30:00+05:30"},
                    },
                    "value": 45.8,
                    "coverage": {"percentComplete": 100.0, "observedCount": 1},
                }
            ]
        },
        request=httpx.Request("GET", "https://api.openaq.org/v3/sensors/12235249/hours"),
    )

    mock_client = MagicMock(spec=httpx.Client)
    # Return hours on first call, meta on second call (or vice versa depending on execution)
    mock_client.request.side_effect = [mock_hours_resp, mock_meta_resp]

    service = OpenAQService(api_key="valid-key", client=mock_client)
    res = service.get_sensor_hours(12235249, limit=5)

    assert res.sensor_id == 12235249
    assert res.parameter_name == "pm25"
    assert res.units == "µg/m³"
    assert res.total_records == 1
    assert res.measurements[0].value == 45.8
    assert res.measurements[0].datetime_from_local == "2024-05-01T15:30:00+05:30"


# ==============================================================================
# TEST 12: Upstream 401 raises OpenAQAuthError with zero retries -> HTTP 502
# ==============================================================================
def test_openaq_upstream_401_auth_error_no_retry():
    mock_resp = httpx.Response(
        status_code=401,
        json={"detail": "Unauthorized API key"},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/6984"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="bad-key", client=mock_client)
    with pytest.raises(OpenAQAuthError):
        service.get_location(6984)

    # Exactly 1 request made — zero automatic retries on 401
    assert mock_client.request.call_count == 1

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 502
    assert "OpenAQ authentication failed" in response.json()["detail"]


# ==============================================================================
# TEST 13: Upstream 429 rate limit preserves Retry-After header with zero retries
# ==============================================================================
def test_openaq_upstream_429_rate_limit_preserves_retry_after():
    mock_resp = httpx.Response(
        status_code=429,
        headers={"Retry-After": "45"},
        json={"detail": "Rate limit exceeded"},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/6984"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    with pytest.raises(OpenAQRatelimitError) as exc_info:
        service.get_location(6984)

    assert exc_info.value.retry_after == 45
    # Fast fail: exactly 1 request made, zero automatic quota-consuming retries
    assert mock_client.request.call_count == 1

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "45"


# ==============================================================================
# TEST 14: Upstream 500 error allows at most 1 controlled retry -> HTTP 502
# ==============================================================================
def test_openaq_upstream_500_server_error_controlled_retry():
    mock_resp = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/6984"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    # max_retries = 1
    service = OpenAQService(api_key="valid-key", max_retries=1, client=mock_client)
    with pytest.raises(OpenAQUpstreamError):
        service.get_location(6984)

    # 1 initial request + 1 controlled retry = exactly 2 attempts
    assert mock_client.request.call_count == 2


# ==============================================================================
# TEST 15: Network timeout allows at most 1 controlled retry -> HTTP 504
# ==============================================================================
def test_openaq_network_timeout_controlled_retry():
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.side_effect = httpx.ReadTimeout("Read timed out")

    # max_retries = 1
    service = OpenAQService(api_key="valid-key", max_retries=1, client=mock_client)
    with pytest.raises(OpenAQTimeoutError):
        service.get_location(6984)

    # 1 initial request + 1 controlled retry = exactly 2 attempts
    assert mock_client.request.call_count == 2

    app.dependency_overrides[get_openaq_service] = lambda: service
    response = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 504


# ==============================================================================
# TEST 16: RBAC Authorization (Unauthenticated 401, Viewer/Analyst/Admin 200)
# ==============================================================================
def test_openaq_rbac_authorization():
    mock_resp = httpx.Response(
        status_code=200,
        json={"results": [SAMPLE_LOCATION_RAW]},
        request=httpx.Request("GET", "https://api.openaq.org/v3/locations/6984"),
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.request.return_value = mock_resp

    service = OpenAQService(api_key="valid-key", client=mock_client)
    app.dependency_overrides[get_openaq_service] = lambda: service

    # 1. Unauthenticated -> 401
    r_unauth = client.get("/api/v1/openaq/locations/6984")
    assert r_unauth.status_code == 401

    # 2. Viewer -> 200
    r_viewer = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r_viewer.status_code == 200

    # 3. Analyst -> 200
    r_analyst = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert r_analyst.status_code == 200

    # 4. Admin -> 200
    r_admin = client.get(
        "/api/v1/openaq/locations/6984",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r_admin.status_code == 200
