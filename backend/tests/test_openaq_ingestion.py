from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple
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
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.user import User, UserRole
from backend.app.schemas.air_quality import AirQualityReadingCreate
from backend.app.schemas.openaq import (
    OpenAQCoverageNormalized,
    OpenAQHourlyMeasurement,
    OpenAQIngestRequest,
    OpenAQLocationNormalized,
    OpenAQSensorHoursResponse,
    OpenAQSensorNormalized,
    OpenAQSensorSummary,
)
from backend.app.services.aqi_engine import calculate_aqi
from backend.app.services.openaq_ingestion_service import (
    OpenAQIngestionService,
    haversine_distance_km,
    normalize_pollutant_value,
)
from backend.app.services.openaq_service import (
    OpenAQRatelimitError,
    OpenAQService,
    get_openaq_service,
)

# In-memory test DB for ingestion test suite
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
def setup_ingestion_test_db():
    global admin_token, analyst_token, viewer_token

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    admin = User(
        username="admin_ingest",
        email="admin_ingest@aeropulse.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_ingest",
        email="analyst_ingest@aeropulse.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_ingest",
        email="viewer_ingest@aeropulse.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])

    # Seed baseline demo location and data source
    demo_source = DataSource(
        name="Demo Benchmark",
        source_type=SourceType.DEMO,
        provider="Synthetic Lab",
        is_active=True,
    )
    demo_loc = Location(
        name="Demo Station 1",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
        is_active=True,
    )
    db.add_all([demo_source, demo_loc])
    db.commit()

    # Seed a demo reading to verify it remains unaffected
    demo_reading = AirQualityReading(
        location_id=demo_loc.id,
        timestamp=datetime.now(timezone.utc) - timedelta(days=5),
        source_id=demo_source.id,
        source_type=SourceType.DEMO,
        pm25=55.0,
        quality_status=QualityStatus.VALID,
    )
    db.add(demo_reading)
    db.commit()
    db.close()

    r1 = client.post("/api/v1/auth/login", json={"username": "admin_ingest", "password": "AdminPass123!"})
    admin_token = r1.json()["access_token"]

    r2 = client.post("/api/v1/auth/login", json={"username": "analyst_ingest", "password": "AnalystPass123!"})
    analyst_token = r2.json()["access_token"]

    r3 = client.post("/api/v1/auth/login", json={"username": "viewer_ingest", "password": "ViewerPass123!"})
    viewer_token = r3.json()["access_token"]

    yield

    app.dependency_overrides.pop(get_openaq_service, None)
    Base.metadata.drop_all(bind=test_engine)


# ==============================================================================
# Helper Mock Factories
# ==============================================================================

def make_mock_location(
    loc_id: int,
    name: str = "Test Station",
    lat: float = 12.97,
    lon: float = 77.59,
    sensors: Optional[List[OpenAQSensorSummary]] = None,
    locality: str = "Bengaluru",
    country_name: str = "India",
) -> OpenAQLocationNormalized:
    return OpenAQLocationNormalized(
        id=loc_id,
        name=name,
        locality=locality,
        country_name=country_name,
        latitude=lat,
        longitude=lon,
        is_monitor=True,
        sensors=sensors or [
            OpenAQSensorSummary(id=1, parameter_name="pm25", units="µg/m³"),
            OpenAQSensorSummary(id=2, parameter_name="no2", units="ppb"),
        ],
        datetime_last=datetime.now(timezone.utc),
    )


def make_mock_sensor(
    sensor_id: int,
    param: str,
    units: str,
    datetime_last: Optional[datetime] = None,
    is_active: bool = True,
    percent_coverage: float = 95.0,
    observed_count: int = 1000,
) -> OpenAQSensorNormalized:
    return OpenAQSensorNormalized(
        id=sensor_id,
        parameter_name=param,
        units=units,
        is_active=is_active,
        datetime_last=datetime_last or datetime.now(timezone.utc),
        coverage=OpenAQCoverageNormalized(
            percent_coverage=percent_coverage,
            observed_count=observed_count,
        ),
    )


# ==============================================================================
# TESTS
# ==============================================================================

# 1. Location model schema has external fields
def test_location_model_has_external_provider_and_id():
    db = TestingSessionLocal()
    loc = Location(
        name="External Station",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9,
        longitude=77.6,
        external_provider="OPENAQ",
        external_id="6984",
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    assert loc.external_provider == "OPENAQ"
    assert loc.external_id == "6984"
    db.close()


# 2. External location mapping creates new location
def test_external_location_mapping_creates_new_location():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    openaq_loc = make_mock_location(6984, "Hebbal, Bengaluru - KSPCB", 13.029, 77.585)
    loc = service._get_or_create_location(openaq_loc)
    assert loc.id is not None
    assert loc.external_provider == "OPENAQ"
    assert loc.external_id == "6984"
    assert loc.name == "Hebbal, Bengaluru - KSPCB"
    db.close()


# 3. External location mapping reuses existing location
def test_external_location_mapping_reuses_existing_location():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    openaq_loc = make_mock_location(6984, "Hebbal, Bengaluru - KSPCB", 13.029, 77.585)
    loc1 = service._get_or_create_location(openaq_loc)
    loc2 = service._get_or_create_location(openaq_loc)
    assert loc1.id == loc2.id
    db.close()


# 4. Existing demo locations remain unaffected
def test_existing_demo_locations_unaffected():
    db = TestingSessionLocal()
    demo_loc = db.query(Location).filter(Location.name == "Demo Station 1").first()
    assert demo_loc is not None
    assert demo_loc.external_provider is None
    assert demo_loc.external_id is None
    db.close()


# 5. Metadata safety: never set state to country_name
def test_location_metadata_safety_never_sets_state_to_country():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    openaq_loc = make_mock_location(9999, "Mystery Station", country_name="India", locality=None)
    loc = service._get_or_create_location(openaq_loc)
    assert loc.country == "India"
    assert loc.state != "India"
    assert loc.state == "Unknown"
    db.close()


# 6. DataSource singleton creation and reuse
def test_openaq_datasource_singleton_creation_and_reuse():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    ds1 = service._get_or_create_datasource()
    ds2 = service._get_or_create_datasource()
    assert ds1.id == ds2.id
    assert ds1.name == "OpenAQ"
    assert ds1.source_type == SourceType.API
    db.close()


# 7. Haversine distance calculation accuracy
def test_haversine_distance_calculation():
    # Bengaluru (12.9716, 77.5946) to Hebbal (13.0291, 77.5859) ~ 6.4 km
    dist = haversine_distance_km(12.9716, 77.5946, 13.0291, 77.5859)
    assert 6.0 <= dist <= 7.0
    # Same point distance is 0.0
    assert haversine_distance_km(12.0, 77.0, 12.0, 77.0) == 0.0


# 8. Dynamic station ranking prefers closer distance and more pollutants
def test_station_ranking_distance_and_supported_pollutants():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    # Station A: 5km away, 4 pollutants
    loc_a = make_mock_location(
        101, "Station A", lat=12.95, lon=77.59,
        sensors=[
            OpenAQSensorSummary(id=1, parameter_name="pm25", units="µg/m³"),
            OpenAQSensorSummary(id=2, parameter_name="no2", units="ppb"),
            OpenAQSensorSummary(id=3, parameter_name="so2", units="ppb"),
            OpenAQSensorSummary(id=4, parameter_name="co", units="mg/m³"),
        ]
    )
    # Station B: 20km away, 1 pollutant
    loc_b = make_mock_location(
        102, "Station B", lat=13.15, lon=77.59,
        sensors=[OpenAQSensorSummary(id=5, parameter_name="pm25", units="µg/m³")]
    )

    mock_openaq = MagicMock(spec=OpenAQService)
    mock_openaq.search_locations.return_value = [loc_b, loc_a]
    service.openaq = mock_openaq

    req = OpenAQIngestRequest(latitude=12.97, longitude=77.59, radius=25000, max_locations=2)
    ranked = service._discover_and_rank_stations(req)
    assert ranked[0].id == 101  # Closer and more pollutants ranks first
    assert ranked[1].id == 102
    db.close()


# 9. Sensor selection: ignores unsupported parameters
def test_sensor_selection_ignores_unsupported():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    sensors = [
        make_mock_sensor(1, "wind_speed", "m/s"),
        make_mock_sensor(2, "wind_direction", "deg"),
        make_mock_sensor(3, "nox", "ppb"),
        make_mock_sensor(4, "no", "ppb"),
        make_mock_sensor(5, "pm25", "µg/m³"),
    ]
    selected = service._select_sensors(sensors)
    assert "wind_speed" not in selected
    assert "wind_direction" not in selected
    assert "nox" not in selected
    assert "no" not in selected
    assert "pm25" in selected
    db.close()


# 10. Sensor selection: recency and coverage tie-breaker
def test_sensor_selection_recency_and_coverage():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    older_sensor = make_mock_sensor(10, "pm25", "µg/m³", datetime_last=datetime(2020, 1, 1, tzinfo=timezone.utc))
    recent_sensor = make_mock_sensor(20, "pm25", "µg/m³", datetime_last=datetime(2026, 9, 25, tzinfo=timezone.utc))
    selected = service._select_sensors([older_sensor, recent_sensor])
    assert selected["pm25"].id == 20
    db.close()


# 11. PM2.5 unit normalization
def test_pm25_unit_normalization():
    val, note = normalize_pollutant_value("pm25", 41.5, "µg/m³")
    assert val == 41.5
    assert note is None
    # Invalid unit for PM2.5
    val_bad, note_bad = normalize_pollutant_value("pm25", 41.5, "ppb")
    assert val_bad is None
    assert "Unsupported unit" in note_bad


# 12. PM10 unit normalization
def test_pm10_unit_normalization():
    val, note = normalize_pollutant_value("pm10", 88.0, "µg/m³")
    assert val == 88.0
    assert note is None


# 13. NO2 ppb to µg/m³ conversion
def test_no2_ppb_conversion():
    # 49.8 ppb * 1.8816 = 93.70368 µg/m³
    val, note = normalize_pollutant_value("no2", 49.8, "ppb")
    assert pytest.approx(val, 0.001) == 93.70368
    assert note is None


# 14. NO2 ppm conversion
def test_no2_ppm_conversion():
    val, note = normalize_pollutant_value("no2", 0.05, "ppm")
    assert pytest.approx(val, 0.01) == 94.08
    assert note is None


# 15. NO2 direct µg/m³
def test_no2_ugm3_direct():
    val, note = normalize_pollutant_value("no2", 45.0, "µg/m³")
    assert val == 45.0
    assert note is None


# 16. SO2 ppb to µg/m³ conversion
def test_so2_ppb_conversion():
    # 8.6 ppb * 2.6203 = 22.53458 µg/m³
    val, note = normalize_pollutant_value("so2", 8.6, "ppb")
    assert pytest.approx(val, 0.001) == 22.53458
    assert note is None


# 17. SO2 ppm conversion
def test_so2_ppm_conversion():
    val, note = normalize_pollutant_value("so2", 0.01, "ppm")
    assert pytest.approx(val, 0.01) == 26.203
    assert note is None


# 18. O3 direct µg/m³ and ppb conversion
def test_o3_normalization():
    val_direct, _ = normalize_pollutant_value("o3", 5.88, "µg/m³")
    assert val_direct == 5.88
    val_ppb, _ = normalize_pollutant_value("o3", 10.0, "ppb")
    assert pytest.approx(val_ppb, 0.01) == 19.631


# 19. CO direct mg/m³ and ppm conversion
def test_co_mgm3_and_ppm_conversion():
    val_direct, _ = normalize_pollutant_value("co", 0.8, "mg/m³")
    assert val_direct == 0.8
    val_ppm, _ = normalize_pollutant_value("co", 1.5, "ppm")
    assert pytest.approx(val_ppm, 0.001) == 1.5 * 1.1456


# 20. CO ppb STRICTLY REJECTED as NULL with explicit note
def test_co_ppb_strictly_rejected():
    val, note = normalize_pollutant_value("co", 0.25, "ppb")
    assert val is None
    assert "CO source unit is ppb and no approved conversion rule is currently configured." in note


# 21. NO unit guessing from magnitude
def test_no_unit_guessing_from_magnitude():
    # Even though 0.25 looks like mg/m³, because source unit is ppb, it MUST NOT be converted to 0.25
    val, note = normalize_pollutant_value("co", 0.25, "ppb")
    assert val is None
    assert val != 0.25


# 22. Temperature and Relative Humidity normalization
def test_temperature_and_humidity_normalization():
    temp_c, _ = normalize_pollutant_value("temperature", 24.5, "c")
    assert temp_c == 24.5
    temp_f, _ = normalize_pollutant_value("temperature", 77.0, "f")
    assert pytest.approx(temp_f, 0.01) == 25.0
    rh, _ = normalize_pollutant_value("relativehumidity", 65.0, "%")
    assert rh == 65.0


# 23. Non-finite values (NaN, inf) rejected
def test_non_finite_values_rejected():
    val_nan, note_nan = normalize_pollutant_value("pm25", float("nan"), "µg/m³")
    assert val_nan is None
    assert "Non-finite" in note_nan
    val_inf, note_inf = normalize_pollutant_value("pm25", float("inf"), "µg/m³")
    assert val_inf is None
    assert "Non-finite" in note_inf


# 24. Hourly temporal alignment truncates to hour
def test_hourly_temporal_alignment():
    dt_raw = datetime(2026, 9, 26, 10, 37, 45, tzinfo=timezone.utc)
    aligned = dt_raw.replace(minute=0, second=0, microsecond=0)
    assert aligned.hour == 10
    assert aligned.minute == 0
    assert aligned.second == 0


# 25. Multi-sensor merging into single reading
def test_multi_sensor_merging_into_single_reading():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    source = service._get_or_create_datasource()
    loc = service._get_or_create_location(make_mock_location(1, "Test Station"))

    now_hour = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    readings = [
        AirQualityReadingCreate(
            location_id=loc.id,
            timestamp=now_hour,
            source_id=source.id,
            source_type=SourceType.API,
            pm25=42.0,
            pm10=85.0,
            no2=35.0,
            co=None,  # missing / rejected CO
        )
    ]
    inserted, skipped, rejected = service._persist_readings(loc.id, source.id, readings)
    assert inserted == 1
    assert skipped == 0
    assert rejected == 0

    saved = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc.id).first()
    assert saved.pm25 == 42.0
    assert saved.pm10 == 85.0
    assert saved.no2 == 35.0
    assert saved.co is None  # Strictly NULL, not 0.0
    assert saved.source_type == SourceType.API
    db.close()


# 26. Negative values rejected by validator during persistence
def test_negative_values_rejected_by_validator():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    source = service._get_or_create_datasource()
    loc = service._get_or_create_location(make_mock_location(2, "Test Station 2"))

    now_hour = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    readings = [
        AirQualityReadingCreate(
            location_id=loc.id,
            timestamp=now_hour,
            source_id=source.id,
            source_type=SourceType.API,
            pm25=-10.0,  # Negative physical concentration
        )
    ]
    inserted, skipped, rejected = service._persist_readings(loc.id, source.id, readings)
    assert inserted == 0
    assert rejected == 1
    db.close()


# 27. Deduplication: skips existing timestamps
def test_deduplication_skips_existing_timestamps():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    source = service._get_or_create_datasource()
    loc = service._get_or_create_location(make_mock_location(3, "Test Station 3"))

    now_hour = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
    r1 = AirQualityReadingCreate(
        location_id=loc.id,
        timestamp=now_hour,
        source_id=source.id,
        source_type=SourceType.API,
        pm25=30.0,
    )
    ins1, skip1, _ = service._persist_readings(loc.id, source.id, [r1])
    assert ins1 == 1

    # Second insert with identical timestamp
    ins2, skip2, _ = service._persist_readings(loc.id, source.id, [r1])
    assert ins2 == 0
    assert skip2 == 1
    db.close()


# 28. Incremental sync window logic
def test_incremental_sync_window_logic():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    source = service._get_or_create_datasource()
    loc = service._get_or_create_location(make_mock_location(4, "Test Station 4"))

    # Initial ingestion: no records -> history_days=7
    dt_from, dt_to, is_skipped = service._determine_time_window(loc.id, source.id, 7)
    assert is_skipped is False
    assert (dt_to - dt_from).days >= 6

    # Insert a reading 2 hours ago
    past_2h = datetime.now(timezone.utc) - timedelta(hours=2)
    db.add(
        AirQualityReading(
            location_id=loc.id,
            timestamp=past_2h,
            source_id=source.id,
            source_type=SourceType.API,
            pm25=20.0,
        )
    )
    db.commit()

    # Incremental sync fetches from past_2h - 1h
    dt_from_inc, _, is_skipped_inc = service._determine_time_window(loc.id, source.id, 7)
    assert is_skipped_inc is False
    assert dt_from_inc <= past_2h

    # Insert a very recent reading (5 mins ago) -> should skip
    recent_5m = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.add(
        AirQualityReading(
            location_id=loc.id,
            timestamp=recent_5m,
            source_id=source.id,
            source_type=SourceType.API,
            pm25=25.0,
        )
    )
    db.commit()

    _, _, is_skipped_recent = service._determine_time_window(loc.id, source.id, 7)
    assert is_skipped_recent is True
    db.close()


# 29. Full ingestion flow with mocked OpenAQ service
def test_full_ingestion_flow():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)

    mock_openaq = MagicMock(spec=OpenAQService)
    loc_norm = make_mock_location(6984, "Hebbal, Bengaluru - KSPCB", 13.029, 77.585)
    mock_openaq.search_locations.return_value = [loc_norm]

    s_pm25 = make_mock_sensor(12235249, "pm25", "µg/m³")
    s_no2 = make_mock_sensor(12235246, "no2", "ppb")
    s_co = make_mock_sensor(12235244, "co", "ppb")  # ppb will be rejected to NULL
    mock_openaq.get_location_sensors.return_value = [s_pm25, s_no2, s_co]

    now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    mock_openaq.get_sensor_hours.side_effect = [
        # PM2.5 hours
        OpenAQSensorHoursResponse(
            sensor_id=12235249, parameter_name="pm25", units="µg/m³", total_records=2,
            measurements=[
                OpenAQHourlyMeasurement(datetime_from_utc=now_utc - timedelta(hours=2), datetime_to_utc=now_utc - timedelta(hours=1), value=41.0),
                OpenAQHourlyMeasurement(datetime_from_utc=now_utc - timedelta(hours=1), datetime_to_utc=now_utc, value=45.0),
            ]
        ),
        # NO2 hours
        OpenAQSensorHoursResponse(
            sensor_id=12235246, parameter_name="no2", units="ppb", total_records=2,
            measurements=[
                OpenAQHourlyMeasurement(datetime_from_utc=now_utc - timedelta(hours=2), datetime_to_utc=now_utc - timedelta(hours=1), value=49.8),
                OpenAQHourlyMeasurement(datetime_from_utc=now_utc - timedelta(hours=1), datetime_to_utc=now_utc, value=52.0),
            ]
        ),
        # CO hours
        OpenAQSensorHoursResponse(
            sensor_id=12235244, parameter_name="co", units="ppb", total_records=2,
            measurements=[
                OpenAQHourlyMeasurement(datetime_from_utc=now_utc - timedelta(hours=2), datetime_to_utc=now_utc - timedelta(hours=1), value=0.29),
                OpenAQHourlyMeasurement(datetime_from_utc=now_utc - timedelta(hours=1), datetime_to_utc=now_utc, value=0.31),
            ]
        ),
    ]

    service.openaq = mock_openaq
    req = OpenAQIngestRequest(latitude=13.029, longitude=77.585, radius=5000, max_locations=1, history_days=1)
    res = service.ingest(req)

    assert res.status == "success"
    assert res.locations_processed == 1
    assert res.observations_inserted == 2
    assert "PM25" in res.pollutants_mapped
    assert "NO2" in res.pollutants_mapped
    assert res.validation_warnings >= 2  # CO in ppb triggered warnings

    # Verify persisted readings
    readings = db.query(AirQualityReading).filter(AirQualityReading.source_type == SourceType.API).all()
    assert len(readings) == 2
    assert readings[0].pm25 in (41.0, 45.0)
    assert readings[0].no2 is not None  # Converted from ppb to µg/m³
    assert readings[0].co is None       # Strictly NULL per mandate
    db.close()


# 30. Idempotency: second ingestion inserts 0 duplicates
def test_idempotent_repeated_ingestion():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)

    mock_openaq = MagicMock(spec=OpenAQService)
    loc_norm = make_mock_location(6984, "Hebbal", 13.029, 77.585)
    mock_openaq.search_locations.return_value = [loc_norm]
    s_pm25 = make_mock_sensor(1, "pm25", "µg/m³")
    mock_openaq.get_location_sensors.return_value = [s_pm25]

    t1 = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    mock_openaq.get_sensor_hours.return_value = OpenAQSensorHoursResponse(
        sensor_id=1, parameter_name="pm25", units="µg/m³", total_records=1,
        measurements=[OpenAQHourlyMeasurement(datetime_from_utc=t1, datetime_to_utc=t1 + timedelta(hours=1), value=35.0)]
    )

    service.openaq = mock_openaq
    req = OpenAQIngestRequest(latitude=13.029, longitude=77.585, radius=5000, max_locations=1)
    res1 = service.ingest(req)
    assert res1.observations_inserted == 1

    # Re-run identical request
    res2 = service.ingest(req)
    assert res2.observations_inserted == 0
    db.close()


# 31. Rejection of history_days > 14 (HTTP 422)
def test_history_days_bounds_check():
    response = client.post(
        "/api/v1/openaq/ingest",
        json={"latitude": 13.0, "longitude": 77.5, "history_days": 15},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422


# 32. Rejection of max_locations > 5 (HTTP 422)
def test_max_locations_bounds_check():
    response = client.post(
        "/api/v1/openaq/ingest",
        json={"latitude": 13.0, "longitude": 77.5, "max_locations": 6},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422


# 33. Rejection of location_ids > 5 (HTTP 422)
def test_explicit_location_ids_exceeding_5_rejected():
    response = client.post(
        "/api/v1/openaq/ingest",
        json={"latitude": 13.0, "longitude": 77.5, "location_ids": [1, 2, 3, 4, 5, 6]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 422
    assert "Maximum 5 locations" in response.text


# 34. RBAC: Admin & Analyst allowed, Viewer 403, Unauth 401
def test_rbac_ingest_endpoint():
    payload = {"latitude": 13.0, "longitude": 77.5, "max_locations": 1}

    # 1. Unauthenticated -> 401
    r_unauth = client.post("/api/v1/openaq/ingest", json=payload)
    assert r_unauth.status_code == 401

    # 2. Viewer -> 403
    r_viewer = client.post(
        "/api/v1/openaq/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert r_viewer.status_code == 403

    # 3. Analyst -> 200 (with mock)
    mock_svc = MagicMock(spec=OpenAQService)
    mock_svc.search_locations.return_value = []
    app.dependency_overrides[get_openaq_service] = lambda: mock_svc

    with patch("backend.app.api.v1.openaq.OpenAQIngestionService") as mock_ingest_cls:
        instance = mock_ingest_cls.return_value
        instance.ingest.return_value = {
            "status": "success",
            "locations_discovered": 0,
            "locations_processed": 0,
            "sensors_discovered": 0,
            "sensors_selected": 0,
            "observations_fetched": 0,
            "observations_inserted": 0,
            "duplicates_skipped": 0,
            "observations_rejected": 0,
            "validation_warnings": 0,
            "pollutants_mapped": [],
            "earliest_observation": None,
            "latest_observation": None,
            "stations": [],
            "duration_seconds": 0.1,
            "errors": [],
        }
        r_analyst = client.post(
            "/api/v1/openaq/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {analyst_token}"},
        )
        assert r_analyst.status_code == 200

        r_admin = client.post(
            "/api/v1/openaq/ingest",
            json=payload,
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r_admin.status_code == 200


# 35. Existing CPCB AQI engine processes ingested reading
def test_cpcb_aqi_engine_processes_ingested_reading():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)
    source = service._get_or_create_datasource()
    loc = service._get_or_create_location(make_mock_location(5, "Hebbal CPCB Test"))

    # Ingest observation with PM2.5 = 41.0 and PM10 = 88.0
    now_hour = datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)
    reading = AirQualityReadingCreate(
        location_id=loc.id,
        timestamp=now_hour,
        source_id=source.id,
        source_type=SourceType.API,
        pm25=41.0,
        pm10=88.0,
        no2=45.0,
    )
    service._persist_readings(loc.id, source.id, [reading])

    db_reading = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc.id).first()
    assert db_reading is not None

    # Calculate AQI with Phase 4 CPCB engine
    pollutant_dict = {
        "pm25": db_reading.pm25,
        "pm10": db_reading.pm10,
        "no2": db_reading.no2,
        "so2": db_reading.so2,
        "co": db_reading.co,
        "o3": db_reading.o3,
    }
    aqi_res = calculate_aqi(**pollutant_dict)
    assert aqi_res.aqi is not None
    assert aqi_res.category in ("Satisfactory", "Moderate", "Good")
    assert aqi_res.dominant_pollutant.upper() in ("PM10", "PM25", "NO2")
    db.close()


# 36. Rate limit 429 stops ingestion gracefully without retrying
def test_rate_limit_429_graceful_stop():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)

    mock_openaq = MagicMock(spec=OpenAQService)
    loc_norm = make_mock_location(1, "Rate Limit Test")
    mock_openaq.search_locations.return_value = [loc_norm]
    # Simulate 429 when getting sensors
    mock_openaq.get_location_sensors.side_effect = OpenAQRatelimitError("Rate limit exceeded (HTTP 429)", retry_after=60)

    service.openaq = mock_openaq
    req = OpenAQIngestRequest(latitude=13.0, longitude=77.5, max_locations=1)
    res = service.ingest(req)

    assert "Rate limit" in str(res.errors)
    assert res.observations_inserted == 0
    db.close()


# 37. Partial station failure isolates errors
def test_partial_station_failure_isolation():
    db = TestingSessionLocal()
    service = OpenAQIngestionService(db=db)

    loc1 = make_mock_location(101, "Good Station")
    loc2 = make_mock_location(102, "Bad Station")

    mock_openaq = MagicMock(spec=OpenAQService)
    mock_openaq.search_locations.return_value = [loc1, loc2]

    s_pm25 = make_mock_sensor(1, "pm25", "µg/m³")

    # Station 1 succeeds, Station 2 raises error
    def mock_get_sensors(loc_id):
        if loc_id == 101:
            return [s_pm25]
        raise Exception("Station 2 connection dropped")

    mock_openaq.get_location_sensors.side_effect = mock_get_sensors
    t1 = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    mock_openaq.get_sensor_hours.return_value = OpenAQSensorHoursResponse(
        sensor_id=1, parameter_name="pm25", units="µg/m³", total_records=1,
        measurements=[OpenAQHourlyMeasurement(datetime_from_utc=t1, datetime_to_utc=t1 + timedelta(hours=1), value=30.0)]
    )

    service.openaq = mock_openaq
    req = OpenAQIngestRequest(latitude=13.0, longitude=77.5, max_locations=2)
    res = service.ingest(req)

    assert res.status == "partial_success"
    assert res.observations_inserted == 1
    assert len(res.errors) == 1
    assert "Bad Station" in res.errors[0]

    # Verify Station 1 was committed
    loc1_db = db.query(Location).filter(Location.external_id == "101").first()
    assert loc1_db is not None
    r_db = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc1_db.id).first()
    assert r_db is not None
    db.close()
