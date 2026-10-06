from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import warnings

import pytest
from starlette.exceptions import StarletteDeprecationWarning

warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
warnings.filterwarnings("ignore", message=".*BlockingPortal.*")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base
from backend.app.core.security import create_access_token
from backend.app.main import app
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import ModelRegistryRecord, PredictionRecord
from backend.app.models.user import User, UserRole
from backend.app.schemas.location_workflow import LocationWorkflowRequest, LocationWorkflowResponse
from backend.app.schemas.openaq import (
    OpenAQLocationNormalized,
    OpenAQSensorHoursResponse,
    OpenAQSensorNormalized,
)
from backend.app.services.location_workflow_service import (
    LocationWorkflowService,
    get_location_workflow_service,
    _LOCATION_RESOLUTION_CACHE,
)
from backend.app.services.openaq_service import (
    OpenAQNotFoundError,
    OpenAQRatelimitError,
    OpenAQUpstreamError,
)

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

    # Clear in-memory cache between tests
    _LOCATION_RESOLUTION_CACHE.clear()

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
    _LOCATION_RESOLUTION_CACHE.clear()


@pytest.fixture
def auth_headers(db_session):
    def _make_headers(role: UserRole = UserRole.VIEWER) -> Dict[str, str]:
        user = User(
            email=f"{role.value.lower()}@aeropulse.org",
            username=f"test_{role.value.lower()}",
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


def make_mock_openaq_location(
    loc_id: int,
    name: str,
    lat: float,
    lon: float,
    pollutants: List[str],
    last_dt: Optional[datetime] = None,
    is_monitor: bool = True,
) -> OpenAQLocationNormalized:
    from backend.app.schemas.openaq import OpenAQSensorSummary
    sensors = [
        OpenAQSensorSummary(
            id=1000 + loc_id * 10 + idx,
            name=f"{p.upper()} Sensor",
            parameter_name=p,
            parameter_display_name=p.upper(),
            units="µg/m³" if p != "co" else "mg/m³",
        )
        for idx, p in enumerate(pollutants)
    ]
    return OpenAQLocationNormalized(
        id=loc_id,
        name=name,
        locality="City Area",
        country_code="IN",
        country_name="India",
        latitude=lat,
        longitude=lon,
        is_monitor=is_monitor,
        datetime_last=last_dt or datetime.now(timezone.utc),
        sensors=sensors,
    )


def make_db_location(
    name: str,
    city: str = "Bengaluru",
    state: str = "Karnataka",
    country: str = "India",
    latitude: float = 13.0,
    longitude: float = 77.0,
    external_provider: str = "OPENAQ",
    external_id: int = 1,
    is_active: bool = True,
) -> Location:
    return Location(
        name=name,
        city=city,
        state=state,
        country=country,
        latitude=latitude,
        longitude=longitude,
        description=f"Station {name}",
        external_provider=external_provider,
        external_id=str(external_id),
        is_active=is_active,
    )


def make_reading(
    location_id: int,
    timestamp: datetime,
    pm25: Optional[float] = 50.0,
    pm10: Optional[float] = None,
    no2: Optional[float] = None,
    so2: Optional[float] = None,
    co: Optional[float] = None,
    o3: Optional[float] = None,
    quality_status: QualityStatus = QualityStatus.VALID,
    source_id: int = 1,
    source_type: SourceType = SourceType.API,
) -> AirQualityReading:
    return AirQualityReading(
        location_id=location_id,
        timestamp=timestamp,
        pm25=pm25,
        pm10=pm10,
        no2=no2,
        so2=so2,
        co=co,
        o3=o3,
        quality_status=quality_status,
        source_id=source_id,
        source_type=source_type,
    )


# ==============================================================================
# 1. Coordinate Validation & OpenAQ Radius Bounds
# ==============================================================================

def test_validation_valid_coordinates(client, auth_headers):
    headers = auth_headers(UserRole.VIEWER)
    # Mock service to avoid upstream call for pure validation test
    with patch.object(LocationWorkflowService, "resolve_location") as mock_resolve:
        mock_resolve.return_value = LocationWorkflowResponse(
            status="NO_STATIONS_FOUND",
            message="No stations",
            user_location={"latitude": 13.0, "longitude": 77.0},
            metadata={
                "duration_seconds": 0.05,
                "cache_hit": False,
                "new_station_discovered": False,
                "observations_ingested": 0,
                "predictions_generated": 0,
                "warnings": [],
            },
        )
        resp = client.post(
            "/api/v1/location-workflow/resolve",
            json={"latitude": 13.0827, "longitude": 80.2707, "radius_meters": 15000},
            headers=headers,
        )
        assert resp.status_code == 200


def test_validation_latitude_out_of_bounds_high(client, auth_headers):
    resp = client.post(
        "/api/v1/location-workflow/resolve",
        json={"latitude": 90.1, "longitude": 77.0},
        headers=auth_headers(),
    )
    assert resp.status_code == 422


def test_validation_latitude_out_of_bounds_low(client, auth_headers):
    resp = client.post(
        "/api/v1/location-workflow/resolve",
        json={"latitude": -90.5, "longitude": 77.0},
        headers=auth_headers(),
    )
    assert resp.status_code == 422


def test_validation_longitude_out_of_bounds_high(client, auth_headers):
    resp = client.post(
        "/api/v1/location-workflow/resolve",
        json={"latitude": 13.0, "longitude": 180.1},
        headers=auth_headers(),
    )
    assert resp.status_code == 422


def test_validation_longitude_out_of_bounds_low(client, auth_headers):
    resp = client.post(
        "/api/v1/location-workflow/resolve",
        json={"latitude": 13.0, "longitude": -180.1},
        headers=auth_headers(),
    )
    assert resp.status_code == 422


def test_validation_radius_negative(client, auth_headers):
    resp = client.post(
        "/api/v1/location-workflow/resolve",
        json={"latitude": 13.0, "longitude": 77.0, "radius_meters": -100},
        headers=auth_headers(),
    )
    assert resp.status_code == 422


def test_validation_radius_exceeds_25km(client, auth_headers):
    resp = client.post(
        "/api/v1/location-workflow/resolve",
        json={"latitude": 13.0, "longitude": 77.0, "radius_meters": 25001},
        headers=auth_headers(),
    )
    assert resp.status_code == 422


def test_validation_boundary_extremes(client, auth_headers):
    with patch.object(LocationWorkflowService, "resolve_location") as mock_resolve:
        mock_resolve.return_value = LocationWorkflowResponse(
            status="NO_STATIONS_FOUND",
            message="Boundary test",
            user_location={"latitude": 90.0, "longitude": 180.0},
            metadata={"duration_seconds": 0.01, "cache_hit": False, "new_station_discovered": False, "observations_ingested": 0, "predictions_generated": 0, "warnings": []},
        )
        resp = client.post(
            "/api/v1/location-workflow/resolve",
            json={"latitude": 90.0, "longitude": 180.0, "radius_meters": 25000},
            headers=auth_headers(),
        )
        assert resp.status_code == 200


# ==============================================================================
# 2. Strict 25 km Boundary & Distant Station Handling
# ==============================================================================

def test_boundary_station_within_radius_resolves(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    # Station at ~5 km
    station_near = make_mock_openaq_location(101, "Near Station", 13.040, 77.500, ["pm25", "pm10"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station_near]):
        with patch.object(service.ingest_service, "ingest") as mock_ingest:
            mock_ingest.return_value.observations_inserted = 0
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.status in ("SUCCESS", "PARTIAL_SUCCESS")
            assert res.resolved_station is not None
            assert res.resolved_station.external_id == 101
            assert res.resolved_station.distance_km <= 25.0
            assert res.nearest_distant_station is None


def test_boundary_station_outside_radius_returns_no_stations_found(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    # Station at ~45 km away
    station_far = make_mock_openaq_location(202, "Distant Station", 13.400, 77.500, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station_far]):
        req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
        res = service.resolve_location(req)
        assert res.status == "NO_STATIONS_FOUND"
        assert res.resolved_station is None
        assert "No official monitoring station was found within 25 km" in res.message


def test_boundary_distant_station_never_becomes_resolved_station(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    station_far = make_mock_openaq_location(303, "Out of Range", 13.500, 77.500, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station_far]):
        req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
        res = service.resolve_location(req)
        assert res.resolved_station is None
        assert res.nearest_distant_station is not None
        assert res.nearest_distant_station.external_id == 303
        assert res.nearest_distant_station.distance_km > 25.0


def test_boundary_distant_station_informational_notice_present(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    station_far = make_mock_openaq_location(404, "Far Station", 13.450, 77.500, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station_far]):
        req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
        res = service.resolve_location(req)
        assert res.nearest_distant_station is not None
        assert "does not represent your immediate local air quality" in res.nearest_distant_station.notice


def test_boundary_custom_smaller_radius_enforced(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    # Station at ~8 km
    station_8km = make_mock_openaq_location(505, "Mid Station", 13.072, 77.500, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station_8km]):
        # Request with 5km radius
        req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=5000)
        res = service.resolve_location(req)
        assert res.status == "NO_STATIONS_FOUND"
        assert res.resolved_station is None
        assert res.nearest_distant_station is not None
        assert res.nearest_distant_station.external_id == 505


# ==============================================================================
# 3. Station Ranking Reuse & Deterministic Selection
# ==============================================================================

def test_ranking_closest_station_prioritized(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    s_close = make_mock_openaq_location(1, "Close Station", 13.010, 77.500, ["pm25"])
    s_far = make_mock_openaq_location(2, "Far Station", 13.100, 77.500, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[s_far, s_close]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station.external_id == 1


def test_ranking_pollutant_completeness_tie_breaker(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    now = datetime.now(timezone.utc)
    # Exactly same distance (~2.2 km)
    s_single = make_mock_openaq_location(10, "Single Pollutant", 13.020, 77.500, ["pm25"], last_dt=now)
    s_multi = make_mock_openaq_location(20, "Multi Pollutant", 13.020, 77.500, ["pm25", "pm10", "no2"], last_dt=now)
    
    with patch.object(service.openaq, "search_locations", return_value=[s_single, s_multi]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station.external_id == 20


def test_ranking_recency_tie_breaker(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    t_old = datetime.now(timezone.utc) - timedelta(hours=10)
    t_new = datetime.now(timezone.utc) - timedelta(minutes=15)
    s_old = make_mock_openaq_location(31, "Old Obs", 13.020, 77.500, ["pm25"], last_dt=t_old)
    s_new = make_mock_openaq_location(32, "New Obs", 13.020, 77.500, ["pm25"], last_dt=t_new)
    
    with patch.object(service.openaq, "search_locations", return_value=[s_old, s_new]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station.external_id == 32


def test_ranking_monitor_flag_tie_breaker(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    now = datetime.now(timezone.utc)
    s_sensor = make_mock_openaq_location(41, "Sensor", 13.020, 77.500, ["pm25"], last_dt=now, is_monitor=False)
    s_monitor = make_mock_openaq_location(42, "Reference Monitor", 13.020, 77.500, ["pm25"], last_dt=now, is_monitor=True)
    
    with patch.object(service.openaq, "search_locations", return_value=[s_sensor, s_monitor]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station.external_id == 42


def test_ranking_id_deterministic_tie_breaker(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    now = datetime.now(timezone.utc)
    s_higher_id = make_mock_openaq_location(55, "Station High ID", 13.020, 77.500, ["pm25"], last_dt=now)
    s_lower_id = make_mock_openaq_location(12, "Station Low ID", 13.020, 77.500, ["pm25"], last_dt=now)
    
    with patch.object(service.openaq, "search_locations", return_value=[s_higher_id, s_lower_id]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station.external_id == 12


def test_ranking_never_bypassed_for_fresh_local_station(db_session):
    """
    Mandatory Correction 1: An existing local station with fresh data must NOT bypass
    authoritative ranking. If station B is closer, B must win even if A is already in the DB.
    """
    # Seed Station A (local in DB, ~10 km away)
    loc_a = make_db_location(
        name="Local Station A",
        city="Bengaluru",
        latitude=13.090,
        longitude=77.500,
        external_provider="OPENAQ",
        external_id=901,
        is_active=True,
    )
    db_session.add(loc_a)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500

    # Station B is much closer (~2 km away)
    openaq_b = make_mock_openaq_location(902, "Closer Station B", 13.018, 77.500, ["pm25"])
    openaq_a = make_mock_openaq_location(901, "Local Station A", 13.090, 77.500, ["pm25"])

    with patch.object(service.openaq, "search_locations", return_value=[openaq_a, openaq_b]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            # Station B MUST win because it is ranked first by distance!
            assert res.resolved_station.external_id == 902


def test_alternative_stations_list_from_same_ranking(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    s1 = make_mock_openaq_location(1, "S1", 13.01, 77.50, ["pm25"])
    s2 = make_mock_openaq_location(2, "S2", 13.03, 77.50, ["pm25"])
    s3 = make_mock_openaq_location(3, "S3", 13.05, 77.50, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[s3, s1, s2]):
        with patch.object(service.ingest_service, "ingest"):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station.external_id == 1
            assert len(res.alternative_stations) == 2
            assert res.alternative_stations[0].external_id == 2
            assert res.alternative_stations[1].external_id == 3


# ==============================================================================
# 4. Actual ML History & Timeline Sufficiency
# ==============================================================================

def test_ml_zero_readings_no_prediction(db_session):
    loc = make_db_location(name="Test Loc 0", external_id=1000)
    db_session.add(loc)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    preds = service._generate_predictions_for_station(loc.id)
    assert len(preds) == 5
    for p in preds:
        assert p.status == "INSUFFICIENT_HISTORY"
        assert p.predicted_aqi is None


def test_ml_one_reading_insufficient_history(db_session):
    loc = make_db_location(name="Test Loc 1", external_id=1001)
    db_session.add(loc)
    db_session.flush()
    r1 = make_reading(location_id=loc.id, timestamp=datetime.now(timezone.utc), pm25=50.0)
    db_session.add(r1)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    preds = service._generate_predictions_for_station(loc.id)
    for p in preds:
        assert p.status == "INSUFFICIENT_HISTORY"
        assert p.predicted_aqi is None


def test_ml_two_readings_insufficient_history(db_session):
    loc = make_db_location(name="Test Loc 2", external_id=1002)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    for i in range(2):
        db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(hours=i), pm25=50.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    preds = service._generate_predictions_for_station(loc.id)
    for p in preds:
        assert p.status == "INSUFFICIENT_HISTORY"
        assert p.predicted_aqi is None


def test_ml_three_readings_insufficient_history(db_session):
    loc = make_db_location(name="Test Loc 3", external_id=1003)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    for i in range(3):
        db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(hours=i), pm25=50.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    preds = service._generate_predictions_for_station(loc.id)
    for p in preds:
        assert p.status == "INSUFFICIENT_HISTORY"
        assert p.predicted_aqi is None


def test_ml_four_continuous_readings_generates_all_five_horizons(db_session):
    loc = make_db_location(name="Test Loc 4", external_id=1004)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    for i in range(4):
        db_session.add(make_reading(
            location_id=loc.id,
            timestamp=now - timedelta(hours=i),
            pm25=45.0,
            pm10=80.0,
            no2=25.0,
            so2=15.0,
            co=0.8,
            o3=30.0,
        ))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch("backend.app.services.location_workflow_service.predict_with_general_model") as mock_predict:
        mock_predict.return_value = {
            "predicted_aqi": 115.0,
            "predicted_category": "Moderate",
            "base_timestamp": now,
            "target_timestamp": now + timedelta(hours=1),
            "model_name": "RandomForestRegressor",
        }
        preds = service._generate_predictions_for_station(loc.id)
        assert len(preds) == 5
        for p in preds:
            assert p.status == "PREDICTED"
            assert p.predicted_aqi == 115.0
            assert p.category == "Moderate"


def test_ml_no_confidence_score_in_response(db_session):
    """
    Mandatory Correction 3: Remove undefined confidence score from schema and response.
    """
    loc = make_db_location(name="Test Loc Schema", external_id=1005)
    db_session.add(loc)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    preds = service._generate_predictions_for_station(loc.id)
    for p in preds:
        d = p.model_dump()
        assert "confidence_score" not in d
        assert "confidence" not in d


def test_ml_reuses_general_model_suite(db_session):
    loc = make_db_location(name="Test General ML", external_id=1006)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(make_reading(
            location_id=loc.id,
            timestamp=now - timedelta(hours=i),
            pm25=50.0,
        ))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch("backend.app.services.location_workflow_service.predict_with_general_model") as mock_predict:
        mock_predict.return_value = {
            "predicted_aqi": 120.0,
            "predicted_category": "Moderate",
            "base_timestamp": now,
            "target_timestamp": now + timedelta(hours=1),
            "model_name": "RandomForestRegressor",
        }
        preds = service._generate_predictions_for_station(loc.id)
        assert mock_predict.called
        # Assert called for all 5 horizons
        horizons_called = [call.kwargs.get("horizon_hours") for call in mock_predict.call_args_list]
        assert sorted(horizons_called) == [1, 3, 6, 12, 24]


# ==============================================================================
# 5. Alert Integration & No New Thresholds
# ==============================================================================

def test_alert_evaluation_called_on_resolved_station(db_session):
    loc = make_db_location(name="Alert Loc", external_id=2001)
    db_session.add(loc)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch("backend.app.services.location_workflow_service.evaluate_location_alerts") as mock_eval:
        with patch("backend.app.services.location_workflow_service.get_active_alerts", return_value=[]):
            alerts = service._evaluate_and_get_alerts(loc.id)
            mock_eval.assert_called_once_with(db_session, location_id=loc.id)
            assert alerts == []


def test_alert_existing_phase10_rules_respected_no_new_thresholds(db_session):
    """
    Mandatory Correction 3: Step 4 must NOT create custom alert thresholds;
    it must directly invoke Phase 10 alert engine.
    """
    service = LocationWorkflowService(db=db_session)
    loc = make_db_location(name="Alert Rules Loc", external_id=2002)
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.location_workflow_service.evaluate_location_alerts") as mock_eval:
        service._evaluate_and_get_alerts(loc.id)
        # Asserts no additional threshold parameters were passed to evaluate_location_alerts
        assert mock_eval.call_args.kwargs == {"location_id": loc.id}


def test_alert_failure_preserves_aqi_and_predictions(db_session):
    service = LocationWorkflowService(db=db_session)
    loc = make_db_location(name="Alert Fail Loc", external_id=2003)
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.location_workflow_service.evaluate_location_alerts", side_effect=RuntimeError("Alert Engine Error")):
        alerts = service._evaluate_and_get_alerts(loc.id)
        assert alerts == []


# ==============================================================================
# 6. Recommendation Integration
# ==============================================================================

def test_recommendation_evaluation_called_on_resolved_station(db_session):
    loc = make_db_location(name="Rec Loc", external_id=3001)
    db_session.add(loc)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch("backend.app.services.location_workflow_service.evaluate_location_recommendations") as mock_eval:
        mock_eval.return_value.recommendations = []
        recs = service._evaluate_and_get_recommendations(loc.id)
        mock_eval.assert_called_once_with(db_session, location_id=loc.id, include_forecast=True, include_alerts=True)
        assert recs == []


def test_recommendation_failure_preserves_upstream_results(db_session):
    service = LocationWorkflowService(db=db_session)
    loc = make_db_location(name="Rec Fail Loc", external_id=3002)
    db_session.add(loc)
    db_session.commit()

    with patch("backend.app.services.location_workflow_service.evaluate_location_recommendations", side_effect=RuntimeError("Rec Error")):
        recs = service._evaluate_and_get_recommendations(loc.id)
        assert recs == []


# ==============================================================================
# 7. Partial Failure Resilience & OpenAQ 429
# ==============================================================================

def test_partial_failure_openaq_429_uses_local_db_station(db_session):
    loc = make_db_location(name="Local Station 429", latitude=13.01, longitude=77.50, external_id=4001, is_active=True)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(minutes=30), pm25=40.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch.object(service.openaq, "search_locations", side_effect=OpenAQRatelimitError("429 Too Many Requests")):
        req = LocationWorkflowRequest(latitude=13.00, longitude=77.50, radius_meters=25000)
        res = service.resolve_location(req)
        assert res.resolved_station is not None
        assert res.resolved_station.external_id == 4001
        assert any("Rate limit" in w for w in res.metadata.warnings)


def test_partial_failure_openaq_5xx_uses_local_db_station(db_session):
    loc = make_db_location(name="Local Station 500", latitude=13.01, longitude=77.50, external_id=5001, is_active=True)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(minutes=45), pm25=55.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch.object(service.openaq, "search_locations", side_effect=OpenAQUpstreamError("502 Bad Gateway")):
        req = LocationWorkflowRequest(latitude=13.00, longitude=77.50, radius_meters=25000)
        res = service.resolve_location(req)
        assert res.resolved_station is not None
        assert res.resolved_station.external_id == 5001
        assert any("Upstream" in w or "502" in w for w in res.metadata.warnings)


def test_partial_failure_ml_exception_preserves_current_aqi(db_session):
    loc = make_db_location(name="Local Station ML Fail", latitude=13.01, longitude=77.50, external_id=6001, is_active=True)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    r = make_reading(location_id=loc.id, timestamp=now, pm25=60.0)
    db_session.add(r)
    db_session.flush()
    aqi_rec = AQIRecord(location_id=loc.id, reading_id=r.id, timestamp=now, aqi=105, category="Moderate", dominant_pollutant="PM2.5", status="CALCULATED")
    db_session.add(aqi_rec)
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    with patch.object(service, "_generate_predictions_for_station", side_effect=RuntimeError("ML Model Crash")):
        with patch.object(service.openaq, "search_locations", return_value=[make_mock_openaq_location(6001, "Local Station ML Fail", 13.01, 77.50, ["pm25"])]):
            req = LocationWorkflowRequest(latitude=13.00, longitude=77.50, radius_meters=25000)
            res = service.resolve_location(req)
            assert res.resolved_station is not None
            assert res.current_aqi is not None
            assert res.current_aqi.aqi == 105
            assert any("Prediction pipeline error" in w for w in res.metadata.warnings)


# ==============================================================================
# 8. In-Memory Spatial Caching & Freshness
# ==============================================================================

def test_cache_hit_on_repeated_nearby_coordinates(db_session):
    service = LocationWorkflowService(db=db_session)
    station = make_mock_openaq_location(7001, "Cached Station", 13.02, 77.50, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station]) as mock_search:
        with patch.object(service.ingest_service, "ingest"):
            # First call: cache miss
            req1 = LocationWorkflowRequest(latitude=13.0211, longitude=77.5011, radius_meters=25000)
            res1 = service.resolve_location(req1)
            assert res1.metadata.cache_hit is False
            assert mock_search.call_count == 1

            # Second call: within ~1.1km grid (same 2 decimal places)
            req2 = LocationWorkflowRequest(latitude=13.0219, longitude=77.5018, radius_meters=25000)
            res2 = service.resolve_location(req2)
            assert res2.metadata.cache_hit is True
            # OpenAQ search was not called again!
            assert mock_search.call_count == 1


def test_cache_force_refresh_bypasses_cache(db_session):
    service = LocationWorkflowService(db=db_session)
    station = make_mock_openaq_location(7002, "Force Refresh Station", 13.02, 77.50, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[station]) as mock_search:
        with patch.object(service.ingest_service, "ingest"):
            req1 = LocationWorkflowRequest(latitude=13.02, longitude=77.50, radius_meters=25000)
            service.resolve_location(req1)
            assert mock_search.call_count == 1

            # Force refresh bypasses cache
            req2 = LocationWorkflowRequest(latitude=13.02, longitude=77.50, radius_meters=25000, force_refresh=True)
            res2 = service.resolve_location(req2)
            assert res2.metadata.cache_hit is False
            assert mock_search.call_count == 2


def test_freshness_status_fresh_under_3h(db_session):
    loc = make_db_location(name="Fresh Loc", external_id=8001)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(minutes=45), pm25=25.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    status, _ = service._determine_data_freshness(loc.id)
    assert status == "FRESH"


def test_freshness_status_stale_between_3h_and_24h(db_session):
    loc = make_db_location(name="Stale Loc", external_id=8002)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(hours=6), pm25=25.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    status, _ = service._determine_data_freshness(loc.id)
    assert status == "STALE"


def test_freshness_status_unavailable_over_24h(db_session):
    loc = make_db_location(name="Unavail Loc", external_id=8003)
    db_session.add(loc)
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(make_reading(location_id=loc.id, timestamp=now - timedelta(hours=30), pm25=25.0))
    db_session.commit()

    service = LocationWorkflowService(db=db_session)
    status, _ = service._determine_data_freshness(loc.id)
    assert status == "UNAVAILABLE"


# ==============================================================================
# 9. Privacy & Logging
# ==============================================================================

def test_privacy_no_gps_database_persistence(db_session):
    """
    Mandatory Correction 2: Precise user coordinates must never be persistently stored.
    Assert that the database tables contain no user GPS columns or history.
    """
    # Inspect tables in SQLite metadata
    tables = Base.metadata.tables.keys()
    assert "user_locations" not in tables
    assert "user_gps_history" not in tables
    assert "user_coordinates" not in tables

    user_cols = [c.name for c in Base.metadata.tables["users"].columns]
    assert "latitude" not in user_cols
    assert "longitude" not in user_cols


def test_privacy_log_sanitization_no_raw_gps(caplog, db_session):
    """
    Mandatory Correction 2: Persistent logs must not output raw high-precision user GPS.
    """
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.0827361, 80.2707294

    with caplog.at_level(logging.INFO):
        with patch.object(service.openaq, "search_locations", return_value=[]):
            req = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000)
            service.resolve_location(req)

    # Full raw precision string must not be present in captured logs
    assert "13.0827361" not in caplog.text
    assert "80.2707294" not in caplog.text


# ==============================================================================
# 10. RBAC
# ==============================================================================

def test_rbac_admin_allowed(client, auth_headers):
    with patch.object(LocationWorkflowService, "resolve_location") as mock_resolve:
        mock_resolve.return_value = LocationWorkflowResponse(
            status="NO_STATIONS_FOUND",
            message="No stations",
            user_location={"latitude": 13.0, "longitude": 77.0},
            metadata={"duration_seconds": 0.01, "cache_hit": False, "new_station_discovered": False, "observations_ingested": 0, "predictions_generated": 0, "warnings": []},
        )
        resp = client.post("/api/v1/location-workflow/resolve", json={"latitude": 13.0, "longitude": 77.0}, headers=auth_headers(UserRole.ADMIN))
        assert resp.status_code == 200


def test_rbac_analyst_allowed(client, auth_headers):
    with patch.object(LocationWorkflowService, "resolve_location") as mock_resolve:
        mock_resolve.return_value = LocationWorkflowResponse(
            status="NO_STATIONS_FOUND",
            message="No stations",
            user_location={"latitude": 13.0, "longitude": 77.0},
            metadata={"duration_seconds": 0.01, "cache_hit": False, "new_station_discovered": False, "observations_ingested": 0, "predictions_generated": 0, "warnings": []},
        )
        resp = client.post("/api/v1/location-workflow/resolve", json={"latitude": 13.0, "longitude": 77.0}, headers=auth_headers(UserRole.ANALYST))
        assert resp.status_code == 200


def test_rbac_viewer_allowed(client, auth_headers):
    with patch.object(LocationWorkflowService, "resolve_location") as mock_resolve:
        mock_resolve.return_value = LocationWorkflowResponse(
            status="NO_STATIONS_FOUND",
            message="No stations",
            user_location={"latitude": 13.0, "longitude": 77.0},
            metadata={"duration_seconds": 0.01, "cache_hit": False, "new_station_discovered": False, "observations_ingested": 0, "predictions_generated": 0, "warnings": []},
        )
        resp = client.post("/api/v1/location-workflow/resolve", json={"latitude": 13.0, "longitude": 77.0}, headers=auth_headers(UserRole.VIEWER))
        assert resp.status_code == 200


def test_rbac_unauthenticated_rejected_401(client):
    resp = client.post("/api/v1/location-workflow/resolve", json={"latitude": 13.0, "longitude": 77.0})
    assert resp.status_code == 401


# ==============================================================================
# 11. Determinism
# ==============================================================================

def test_determinism_identical_inputs_produce_identical_selection(db_session):
    service = LocationWorkflowService(db=db_session)
    user_lat, user_lon = 13.000, 77.500
    s1 = make_mock_openaq_location(1, "Station 1", 13.02, 77.50, ["pm25"])
    s2 = make_mock_openaq_location(2, "Station 2", 13.04, 77.50, ["pm25"])
    
    with patch.object(service.openaq, "search_locations", return_value=[s2, s1]):
        with patch.object(service.ingest_service, "ingest"):
            req1 = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000, force_refresh=True)
            res1 = service.resolve_location(req1)

            req2 = LocationWorkflowRequest(latitude=user_lat, longitude=user_lon, radius_meters=25000, force_refresh=True)
            res2 = service.resolve_location(req2)

            assert res1.resolved_station.external_id == res2.resolved_station.external_id
            assert res1.resolved_station.external_id == 1
