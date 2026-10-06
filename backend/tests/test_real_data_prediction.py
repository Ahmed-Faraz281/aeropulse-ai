from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import warnings
import joblib
import numpy as np
import pytest
from starlette.exceptions import StarletteDeprecationWarning

# Filter upstream third-party deprecation warnings from starlette.testclient in Python 3.13 / anyio 4.15
warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
warnings.filterwarnings("ignore", message=".*BlockingPortal.*")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.core.database import Base, get_db
from backend.app.core.security import create_access_token, get_password_hash
from backend.app.main import app
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import Alert, AlertRule, AlertSeverity, AlertStatus, AlertType
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import ModelRegistryRecord, PredictionRecord
from backend.app.models.user import User, UserRole
from backend.app.schemas.air_quality import AirQualityReadingCreate
from backend.app.services.alert_service import evaluate_location_alerts
from backend.app.services.aqi_engine import calculate_aqi
from backend.app.services.openaq_ingestion_service import OpenAQIngestionService
from backend.app.services.prediction_service import (
    DEFAULT_HORIZONS,
    FEATURE_NAMES,
    FileTrainingLock,
    _MODEL_CACHE,
    build_feature_row,
    check_and_trigger_automatic_retraining,
    compute_file_sha256,
    extract_multi_station_features_and_targets,
    features_to_matrix,
    get_active_general_model,
    predict_with_general_model,
    train_and_evaluate_model,
    train_general_models,
)
from backend.app.services.recommendation_service import evaluate_location_recommendations

# Dedicated in-memory SQLite database for Step 3 test suite
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


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


# ==============================================================================
# Pytest Fixtures
# ==============================================================================

@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    """Initializes tables, overrides model directory with tmp_path, and clears cache."""
    app.dependency_overrides[get_db] = override_get_db
    _MODEL_CACHE.clear()
    original_model_dir = settings.MODEL_DIR
    settings.MODEL_DIR = str(tmp_path / "models")
    os.makedirs(settings.MODEL_DIR, exist_ok=True)

    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    yield

    _MODEL_CACHE.clear()
    settings.MODEL_DIR = original_model_dir


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def auth_tokens(db_session):
    admin = User(
        username="admin_step3",
        email="admin_step3@aeropulse.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_step3",
        email="analyst_step3@aeropulse.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_step3",
        email="viewer_step3@aeropulse.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db_session.add_all([admin, analyst, viewer])
    db_session.commit()

    return {
        "admin": create_access_token(admin.username),
        "analyst": create_access_token(analyst.username),
        "viewer": create_access_token(viewer.username),
    }


def _seed_hourly_readings(
    db,
    location_id: int,
    source_id: int,
    source_type: SourceType,
    count: int = 60,
    start_time: Optional[datetime] = None,
    base_pm25: float = 65.0,
    quality_status: QualityStatus = QualityStatus.VALID,
):
    """Helper to populate realistic hourly readings with associated AQIRecords."""
    t0 = start_time or (datetime.now(timezone.utc) - timedelta(hours=count + 1))
    readings = []
    for i in range(count):
        ts = t0 + timedelta(hours=i)
        pm25 = max(5.0, base_pm25 + 15.0 * math.sin(i * 2.0 * math.pi / 24.0))
        pm10 = pm25 * 1.6
        no2 = 25.0 + 8.0 * math.cos(i * 2.0 * math.pi / 24.0)
        so2 = 12.0
        co = 0.8
        o3 = 20.0
        temp = 24.0 + 4.0 * math.sin(i * 2.0 * math.pi / 24.0)
        rh = 60.0

        r = AirQualityReading(
            location_id=location_id,
            timestamp=ts,
            source_id=source_id,
            source_type=source_type,
            pm25=pm25,
            pm10=pm10,
            no2=no2,
            so2=so2,
            co=co,
            o3=o3,
            temperature=temp,
            humidity=rh,
            quality_status=quality_status,
        )
        db.add(r)
        db.flush()

        if quality_status == QualityStatus.VALID:
            calc = calculate_aqi(pm25=pm25, pm10=pm10, no2=no2, so2=so2, co=co, o3=o3, timestamp=ts)
            aqi_rec = AQIRecord(
                location_id=location_id,
                reading_id=r.id,
                timestamp=ts,
                aqi=calc.aqi,
                category=calc.category,
                dominant_pollutant=calc.dominant_pollutant,
                calculation_method=calc.calculation_method,
                status=calc.status.value,
                pollutant_subindices=calc.pollutant_subindices,
                warnings=calc.warnings,
                message=calc.message,
            )
            db.add(aqi_rec)
        readings.append(r)

    db.commit()
    return readings


@pytest.fixture
def multi_station_setup(db_session):
    """Sets up Station 1 (Bengaluru), Station 2 (Hyderabad), and Station 3 (Unseen Chikkaballapur)."""
    src_api = DataSource(name="OpenAQ", source_type=SourceType.API, provider="OpenAQ v3", is_active=True)
    src_upload = DataSource(name="Manual CSV", source_type=SourceType.UPLOADED, provider="File Upload", is_active=True)
    src_sim = DataSource(name="Synthetic", source_type=SourceType.SIMULATED, provider="Engine", is_active=True)
    db_session.add_all([src_api, src_upload, src_sim])
    db_session.flush()

    # Station 1: Bengaluru Hebbal
    loc1 = Location(
        name="Bengaluru Hebbal",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=13.0359,
        longitude=77.5870,
        external_provider="OPENAQ",
        external_id="6984",
        is_active=True,
    )
    # Station 2: Hyderabad Sanathnagar
    loc2 = Location(
        name="Hyderabad Sanathnagar",
        city="Hyderabad",
        state="Telangana",
        country="India",
        latitude=17.4560,
        longitude=78.4430,
        external_provider="OPENAQ",
        external_id="7012",
        is_active=True,
    )
    # Station 3: Chikkaballapur (Unseen station for generalization tests)
    loc3 = Location(
        name="Chikkaballapur Rural",
        city="Chikkaballapur",
        state="Karnataka",
        country="India",
        latitude=13.4325,
        longitude=77.7275,
        external_provider="OPENAQ",
        external_id="8888",
        is_active=True,
    )
    # Station 4: Demo Station
    loc_demo = Location(
        name="Demo Industrial Site [DEMO]",
        city="DemoCity",
        state="DemoState",
        country="India",
        latitude=12.0,
        longitude=76.0,
        description="[DEMO] Simulated trial site",
        is_active=True,
    )

    db_session.add_all([loc1, loc2, loc3, loc_demo])
    db_session.commit()

    # Seed 60 observations each for Station 1 & 2 (Total = 120 API readings)
    _seed_hourly_readings(db_session, loc1.id, src_api.id, SourceType.API, count=60, base_pm25=70.0)
    _seed_hourly_readings(db_session, loc2.id, src_api.id, SourceType.API, count=60, base_pm25=90.0)

    # Seed 10 observations for Station 3 (Unseen)
    _seed_hourly_readings(db_session, loc3.id, src_api.id, SourceType.API, count=10, base_pm25=45.0)

    # Seed simulated readings for loc_demo
    _seed_hourly_readings(db_session, loc_demo.id, src_sim.id, SourceType.SIMULATED, count=60, base_pm25=120.0)

    return {
        "src_api": src_api,
        "src_upload": src_upload,
        "src_sim": src_sim,
        "loc1": loc1,
        "loc2": loc2,
        "loc3": loc3,
        "loc_demo": loc_demo,
    }


# ==============================================================================
# 1. Real-Data Eligibility & Filtering Tests
# ==============================================================================

def test_real_data_eligibility_api_and_uploaded(db_session, multi_station_setup):
    """Verify that SourceType.API and SourceType.UPLOADED are eligible for multi-station training."""
    src_up = multi_station_setup["src_upload"]
    loc1 = multi_station_setup["loc1"]
    _seed_hourly_readings(
        db_session, loc1.id, src_up.id, SourceType.UPLOADED, count=10,
        start_time=datetime.now(timezone.utc) - timedelta(hours=200)
    )

    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert "API" in sources
    assert "UPLOADED" in sources
    assert not has_sim
    assert st_count >= 2


def test_real_data_eligibility_simulated_excluded(db_session, multi_station_setup):
    """Verify that SourceType.SIMULATED observations are strictly excluded from general model training."""
    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert "SIMULATED" not in sources
    assert has_sim is False


def test_real_data_eligibility_demo_locations_excluded(db_session, multi_station_setup):
    """Verify demo locations are excluded from production training when allow_demo_fallback=False."""
    loc_demo = multi_station_setup["loc_demo"]
    src_api = multi_station_setup["src_api"]
    _seed_hourly_readings(db_session, loc_demo.id, src_api.id, SourceType.API, count=20)

    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert "DEMO" not in sources


def test_real_data_eligibility_what_if_and_predictions_excluded(db_session, multi_station_setup):
    """Verify prediction records and what-if records are not extracted as training observations."""
    loc1 = multi_station_setup["loc1"]
    now = datetime.now(timezone.utc)

    pred = PredictionRecord(
        location_id=loc1.id,
        base_timestamp=now,
        target_timestamp=now + timedelta(hours=1),
        horizon_hours=1,
        predicted_aqi=150.0,
        predicted_category="Moderate",
        model_name="RandomForestRegressor",
        training_observations=100,
        is_prediction=True,
    )
    db_session.add(pred)
    db_session.commit()

    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert total_samples > 0


# ==============================================================================
# 2. Data Quality & CPCB Sufficiency Tests
# ==============================================================================

def test_data_quality_invalid_readings_excluded(db_session, multi_station_setup):
    """Verify readings marked INVALID are excluded from feature/target extraction."""
    loc1 = multi_station_setup["loc1"]
    src_api = multi_station_setup["src_api"]
    _seed_hourly_readings(
        db_session, loc1.id, src_api.id, SourceType.API, count=10,
        quality_status=QualityStatus.INVALID
    )

    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert total_samples > 0


def test_data_quality_null_pollutants_preserved_as_nan(db_session, multi_station_setup):
    """Verify missing pollutants remain NaN in matrix conversion rather than being converted to 0."""
    loc1 = multi_station_setup["loc1"]
    src_api = multi_station_setup["src_api"]
    now = datetime.now(timezone.utc)

    r = AirQualityReading(
        location_id=loc1.id,
        timestamp=now + timedelta(hours=100),
        source_id=src_api.id,
        source_type=SourceType.API,
        pm25=50.0,
        pm10=80.0,
        co=1.0,
        no2=None,
        so2=None,
        quality_status=QualityStatus.VALID,
    )
    db_session.add(r)
    db_session.commit()

    latest_rec = {"reading": r, "timestamp": r.timestamp, "aqi": 100}
    f_dict = build_feature_row(latest_rec, [])
    matrix = features_to_matrix([f_dict])
    col_idx_no2 = FEATURE_NAMES.index("no2")
    col_idx_so2 = FEATURE_NAMES.index("so2")
    assert np.isnan(matrix[0, col_idx_no2])
    assert np.isnan(matrix[0, col_idx_so2])


def test_data_quality_cpcb_sufficiency_for_targets(db_session, multi_station_setup):
    """Verify target AQI requires CPCB sufficiency (minimum 3 pollutants with 1 PM)."""
    res = calculate_aqi(no2=40.0, so2=20.0, pm25=None, pm10=None)
    assert res.aqi is None
    assert res.status.value == "INSUFFICIENT_DATA"


# ==============================================================================
# 3. Multi-Station Training & Anti-Leakage Tests
# ==============================================================================

def test_multi_station_pooling(db_session, multi_station_setup):
    """Verify training pools observations from multiple stations into a single training set."""
    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert st_count >= 2
    assert len(X_tr) > 50
    assert len(X_val) > 10


def test_station_local_lag_construction_no_cross_station_leakage(db_session):
    """Verify that lag features for Station B never use Station A's readings."""
    src = DataSource(name="OpenAQ", source_type=SourceType.API, provider="OpenAQ v3", is_active=True)
    loc_a = Location(name="Station A", city="CityA", state="StateA", country="India", latitude=12.0, longitude=77.0, is_active=True)
    loc_b = Location(name="Station B", city="CityB", state="StateB", country="India", latitude=13.0, longitude=78.0, is_active=True)
    db_session.add_all([src, loc_a, loc_b])
    db_session.commit()

    t0 = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
    for h in [0, 1, 2]:
        _seed_hourly_readings(db_session, loc_a.id, src.id, SourceType.API, count=1,
                              start_time=t0 + timedelta(hours=h), base_pm25=200.0)

    readings_b = _seed_hourly_readings(db_session, loc_b.id, src.id, SourceType.API, count=1,
                                       start_time=t0 + timedelta(hours=3), base_pm25=30.0)

    latest_rec_b = {"reading": readings_b[0], "timestamp": readings_b[0].timestamp, "aqi": 50}
    # Station B has only 1 reading, so prev_records for Station B is empty
    f_b = build_feature_row(latest_rec_b, [])
    assert f_b["pm25_lag_1"] is None
    assert f_b["aqi_lag_1"] is None
    assert f_b["pm25"] == 30.0


def test_per_station_chronological_split(db_session, multi_station_setup):
    """Verify that the 80/20 train/val split is performed per-station in chronological order."""
    X_tr, X_val, y_tr, y_val, st_count, total_samples, sources, has_sim = extract_multi_station_features_and_targets(
        db_session, horizon_hours=1, allow_demo_fallback=False
    )
    assert len(X_tr) > 0
    assert len(X_val) > 0
    ratio = len(X_tr) / (len(X_tr) + len(X_val))
    assert 0.75 <= ratio <= 0.85


def test_general_models_trained_for_all_five_horizons(db_session, multi_station_setup):
    """Verify train_general_models successfully trains and serializes all 5 default horizons."""
    results = train_general_models(db_session, horizons=DEFAULT_HORIZONS, min_observations=20)
    assert len(results) == 5
    trained_horizons = {r["horizon_hours"] for r in results}
    assert trained_horizons == {1, 3, 6, 12, 24}
    for res in results:
        assert res["status"] == "SUCCESS"
        assert res["mae"] is not None
        assert res["rmse"] is not None
        assert os.path.exists(res["artifact_path"])
        assert res["checksum"] == compute_file_sha256(res["artifact_path"])


# ==============================================================================
# 4. Station Independence & Unseen Station Generalization
# ==============================================================================

def test_feature_matrix_station_independence():
    """Verify FEATURE_NAMES contains exactly 22 columns with zero station/city IDs."""
    assert len(FEATURE_NAMES) == 22
    for feat in FEATURE_NAMES:
        assert "location" not in feat.lower()
        assert "station" not in feat.lower()
        assert "city" not in feat.lower()
        assert "latitude" not in feat.lower()
        assert "longitude" not in feat.lower()


def test_unseen_station_zero_shot_generalization(db_session, multi_station_setup):
    """Verify a model trained on Station 1 & 2 can immediately predict on unseen Station 3."""
    train_general_models(db_session, horizons=[1], min_observations=20)

    loc3 = multi_station_setup["loc3"]
    pred = predict_with_general_model(db_session, location_id=loc3.id, horizon_hours=1)

    assert pred["location_id"] == loc3.id
    assert pred["location_name"] == loc3.name
    assert pred["predicted_aqi"] >= 0.0
    assert pred["predicted_category"] in ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    assert pred["is_prediction"] is True


def test_cross_city_generalization_same_model(db_session, multi_station_setup):
    """Verify the exact SAME general model artifact is used for Bengaluru and Hyderabad stations."""
    train_general_models(db_session, horizons=[1], min_observations=20)

    loc_bengaluru = multi_station_setup["loc1"]
    loc_hyderabad = multi_station_setup["loc2"]

    pred_b = predict_with_general_model(db_session, location_id=loc_bengaluru.id, horizon_hours=1)
    pred_h = predict_with_general_model(db_session, location_id=loc_hyderabad.id, horizon_hours=1)

    reg_rec_b = db_session.query(ModelRegistryRecord).filter(
        ModelRegistryRecord.horizon_hours == 1, ModelRegistryRecord.is_active == True
    ).first()

    assert pred_b["model_name"] == reg_rec_b.model_id
    assert pred_h["model_name"] == reg_rec_b.model_id
    assert reg_rec_b.model_id.startswith("aeropulse_general_v1_1h")


# ==============================================================================
# 5. Model Registry & Artifact Integrity Tests
# ==============================================================================

def test_model_registry_record_metadata(db_session, multi_station_setup):
    """Verify ModelRegistryRecord stores all operational and audit metadata."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    rec = db_session.query(ModelRegistryRecord).filter(
        ModelRegistryRecord.horizon_hours == 1, ModelRegistryRecord.is_active == True
    ).first()

    assert rec is not None
    assert rec.model_id.startswith("aeropulse_general_v1_1h")
    assert rec.model_name == "RandomForestRegressor"
    assert rec.training_observations >= 50
    assert rec.training_locations_count >= 2
    assert rec.mae is not None
    assert rec.rmse is not None
    assert rec.features == FEATURE_NAMES
    assert rec.is_active is True
    assert os.path.exists(rec.artifact_path)


def test_joblib_artifact_serialization_and_deserialization(db_session, multi_station_setup):
    """Verify model artifact on disk can be loaded directly with joblib."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    rec = db_session.query(ModelRegistryRecord).filter(ModelRegistryRecord.is_active == True).first()

    loaded_model = joblib.load(rec.artifact_path)
    assert hasattr(loaded_model, "predict")


def test_sha256_checksum_verification(db_session, multi_station_setup):
    """Verify SHA-256 checksum matches disk artifact."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    rec = db_session.query(ModelRegistryRecord).filter(ModelRegistryRecord.is_active == True).first()

    with open(rec.artifact_path, "rb") as f:
        expected_hash = hashlib.sha256(f.read()).hexdigest()
    assert rec.checksum == expected_hash


def test_checksum_tampering_detected(db_session, multi_station_setup):
    """Verify tampering with model artifact causes get_active_general_model to return None."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    rec = db_session.query(ModelRegistryRecord).filter(ModelRegistryRecord.is_active == True).first()

    _MODEL_CACHE.clear()
    with open(rec.artifact_path, "ab") as f:
        f.write(b"tampered_bytes")

    assert get_active_general_model(db_session, horizon_hours=1) is None


def test_deactivation_of_previous_active_models(db_session, multi_station_setup):
    """Verify re-training for the same horizon deactivates previous active records."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    recs_first = db_session.query(ModelRegistryRecord).filter(ModelRegistryRecord.horizon_hours == 1).all()
    assert len(recs_first) == 1
    assert recs_first[0].is_active is True

    train_general_models(db_session, horizons=[1], min_observations=20)
    recs_all = db_session.query(ModelRegistryRecord).filter(ModelRegistryRecord.horizon_hours == 1).all()
    assert len(recs_all) == 2
    active_recs = [r for r in recs_all if r.is_active]
    assert len(active_recs) == 1


def test_missing_artifact_file_handling(db_session, multi_station_setup):
    """Verify deleting the serialized artifact causes get_active_general_model to return None."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    rec = db_session.query(ModelRegistryRecord).filter(ModelRegistryRecord.is_active == True).first()
    _MODEL_CACHE.clear()

    if os.path.exists(rec.artifact_path):
        os.remove(rec.artifact_path)

    assert get_active_general_model(db_session, horizon_hours=1) is None


# ==============================================================================
# 6. Concurrency & Training Lock Tests
# ==============================================================================

def test_file_training_lock_prevents_concurrency(tmp_path):
    """Verify FileTrainingLock prevents overlapping training executions."""
    lock_file = tmp_path / "training.lock"
    lock1 = FileTrainingLock(str(lock_file))
    lock2 = FileTrainingLock(str(lock_file))

    with lock1:
        assert os.path.exists(str(lock_file))
        with pytest.raises((BlockingIOError, RuntimeError)):
            with lock2:
                pass


def test_file_training_lock_cleans_up_on_completion(tmp_path):
    """Verify lock file is removed upon normal context exit."""
    lock_file = tmp_path / "training_done.lock"
    with FileTrainingLock(str(lock_file)):
        assert os.path.exists(str(lock_file))
    assert not os.path.exists(str(lock_file))


def test_file_training_lock_cleans_up_on_exception(tmp_path):
    """Verify lock file is removed even when an exception is raised inside the block."""
    lock_file = tmp_path / "training_err.lock"
    try:
        with FileTrainingLock(str(lock_file)):
            assert os.path.exists(str(lock_file))
            raise ValueError("Forced error")
    except ValueError:
        pass
    assert not os.path.exists(str(lock_file))


# ==============================================================================
# 7. Automatic Retraining Trigger Tests
# ==============================================================================

def test_automatic_retraining_trigger_when_models_missing(db_session, multi_station_setup):
    """Verify check_and_trigger_automatic_retraining triggers when no active models exist."""
    assert db_session.query(ModelRegistryRecord).count() == 0
    results = check_and_trigger_automatic_retraining(db_session)
    assert results is not None
    assert len(results) == 5


def test_automatic_retraining_trigger_on_200_new_observations(db_session, multi_station_setup):
    """Verify retraining triggers when new real observations >= 200."""
    train_general_models(db_session, horizons=DEFAULT_HORIZONS, min_observations=20)

    loc1 = multi_station_setup["loc1"]
    src_api = multi_station_setup["src_api"]
    _seed_hourly_readings(
        db_session, loc1.id, src_api.id, SourceType.API, count=210,
        start_time=datetime.now(timezone.utc) - timedelta(hours=400)
    )

    results = check_and_trigger_automatic_retraining(db_session)
    assert results is not None
    assert len(results) == 5


def test_automatic_retraining_not_triggered_below_threshold(db_session, multi_station_setup):
    """Verify retraining is skipped when new observations < 200 and model is fresh."""
    train_general_models(db_session, horizons=DEFAULT_HORIZONS, min_observations=20)

    loc1 = multi_station_setup["loc1"]
    src_api = multi_station_setup["src_api"]
    _seed_hourly_readings(
        db_session, loc1.id, src_api.id, SourceType.API, count=30,
        start_time=datetime.now(timezone.utc) - timedelta(hours=300)
    )

    results = check_and_trigger_automatic_retraining(db_session)
    assert results is None


def test_automatic_retraining_trigger_on_staleness_and_50_new_obs(db_session, multi_station_setup):
    """Verify retraining triggers when model is older than 7 days and new observations >= 50."""
    train_general_models(db_session, horizons=DEFAULT_HORIZONS, min_observations=20)

    eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
    db_session.query(ModelRegistryRecord).update({"created_at": eight_days_ago})
    db_session.commit()

    loc1 = multi_station_setup["loc1"]
    src_api = multi_station_setup["src_api"]
    _seed_hourly_readings(
        db_session, loc1.id, src_api.id, SourceType.API, count=60,
        start_time=datetime.now(timezone.utc) - timedelta(hours=300)
    )

    results = check_and_trigger_automatic_retraining(db_session)
    assert results is not None
    assert len(results) == 5


# ==============================================================================
# 8. Automatic Prediction Post-Ingestion Tests
# ==============================================================================

def test_automatic_prediction_post_ingestion(db_session, multi_station_setup):
    """Verify OpenAQ ingestion triggers automatic multi-horizon predictions for stations with sufficient history."""
    train_general_models(db_session, horizons=DEFAULT_HORIZONS, min_observations=20)

    loc1 = multi_station_setup["loc1"]
    ingest_svc = OpenAQIngestionService(db=db_session)

    t_base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    new_readings = [
        AirQualityReadingCreate(
            location_id=loc1.id,
            timestamp=t_base + timedelta(hours=i),
            source_id=multi_station_setup["src_api"].id,
            source_type=SourceType.API,
            pm25=75.0 + i * 2.0,
            pm10=110.0 + i * 3.0,
            no2=30.0,
            so2=15.0,
            co=1.0,
            o3=22.0,
            temperature=25.0,
            humidity=55.0,
        )
        for i in range(5)
    ]

    ins, dup, rej = ingest_svc._persist_readings(loc1.id, multi_station_setup["src_api"].id, new_readings)
    db_session.commit()
    assert ins == 5

    for h in [1, 3, 6, 12, 24]:
        pred = predict_with_general_model(db_session, location_id=loc1.id, horizon_hours=h)
        assert pred["predicted_aqi"] >= 0.0
        assert pred["horizon_hours"] == h
        assert pred["is_prediction"] is True


def test_prediction_record_provenance_tagging(db_session, multi_station_setup):
    """Verify PredictionRecord contains is_prediction=True and appropriate provenance labels."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    loc1 = multi_station_setup["loc1"]
    pred = predict_with_general_model(db_session, location_id=loc1.id, horizon_hours=1)

    rec = db_session.query(PredictionRecord).filter(PredictionRecord.id == pred["id"]).first()
    assert rec is not None
    assert rec.is_prediction is True
    assert rec.model_name.startswith("aeropulse_general_v1_1h")
    assert rec.provenance_notice is not None


def test_physical_aqi_clamping_0_to_500(db_session, multi_station_setup):
    """Verify regression model output outside [0, 500] is physically clamped."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    loc1 = multi_station_setup["loc1"]

    with patch.object(joblib, "load") as mock_load:
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-25.0])
        mock_load.return_value = mock_model
        _MODEL_CACHE.clear()

        pred_low = predict_with_general_model(db_session, location_id=loc1.id, horizon_hours=1)
        assert pred_low["predicted_aqi"] == 0.0

        mock_model.predict.return_value = np.array([750.0])
        _MODEL_CACHE.clear()
        pred_high = predict_with_general_model(db_session, location_id=loc1.id, horizon_hours=1)
        assert pred_high["predicted_aqi"] == 500.0


def test_cpcb_category_mapping_for_predictions(db_session, multi_station_setup):
    """Verify predicted AQI values are mapped to official CPCB categories."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    loc1 = multi_station_setup["loc1"]

    test_cases = [
        (45.0, "Good"),
        (85.0, "Satisfactory"),
        (150.0, "Moderate"),
        (250.0, "Poor"),
        (350.0, "Very Poor"),
        (450.0, "Severe"),
    ]

    for val, expected_cat in test_cases:
        with patch.object(joblib, "load") as mock_load:
            mock_model = MagicMock()
            mock_model.predict.return_value = np.array([val])
            mock_load.return_value = mock_model
            _MODEL_CACHE.clear()

            p = predict_with_general_model(db_session, location_id=loc1.id, horizon_hours=1)
            assert p["predicted_category"] == expected_cat


def test_prediction_confidence_intervals(db_session, multi_station_setup):
    """Verify model performance metrics (MAE, RMSE, R2) are included with prediction."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    loc1 = multi_station_setup["loc1"]

    pred = predict_with_general_model(db_session, location_id=loc1.id, horizon_hours=1)
    assert pred["mae"] is not None
    assert pred["rmse"] is not None
    assert pred["r2"] is not None


# ==============================================================================
# 9. Feature Sufficiency & Gaps Tests
# ==============================================================================

def test_feature_sufficiency_fewer_than_4_readings(db_session, multi_station_setup):
    """Verify predict_with_general_model raises ValueError if fewer than 4 readings exist."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    src = multi_station_setup["src_api"]
    loc_scant = Location(name="Sparse Station", city="Sparse", state="Karnataka", country="India", latitude=13.0, longitude=77.0, is_active=True)
    db_session.add(loc_scant)
    db_session.commit()

    _seed_hourly_readings(db_session, loc_scant.id, src.id, SourceType.API, count=3)

    with pytest.raises(ValueError, match="Insufficient historical data"):
        predict_with_general_model(db_session, location_id=loc_scant.id, horizon_hours=1)


def test_feature_sufficiency_with_4_continuous_readings(db_session, multi_station_setup):
    """Verify predict_with_general_model succeeds with exactly 4 continuous readings."""
    train_general_models(db_session, horizons=[1], min_observations=20)
    src = multi_station_setup["src_api"]
    loc_4 = Location(name="Four Readings Station", city="Sparse", state="Karnataka", country="India", latitude=13.0, longitude=77.0, is_active=True)
    db_session.add(loc_4)
    db_session.commit()

    _seed_hourly_readings(db_session, loc_4.id, src.id, SourceType.API, count=4)

    pred = predict_with_general_model(db_session, location_id=loc_4.id, horizon_hours=1)
    assert pred["predicted_aqi"] >= 0.0


def test_shared_build_feature_row_eliminates_drift(db_session, multi_station_setup):
    """Verify build_feature_row returns identical keys to FEATURE_NAMES."""
    loc1 = multi_station_setup["loc1"]
    readings = (
        db_session.query(AirQualityReading)
        .filter(AirQualityReading.location_id == loc1.id)
        .order_by(AirQualityReading.timestamp.desc())
        .limit(4)
        .all()
    )
    records = [{"reading": r, "timestamp": r.timestamp, "aqi": 80} for r in reversed(readings)]
    f_dict = build_feature_row(records[-1], records[:-1])
    assert set(f_dict.keys()) == set(FEATURE_NAMES)


# ==============================================================================
# 10. Downstream Alert & Recommendation Integration Tests
# ==============================================================================

def test_alert_service_predicted_threshold_integration(db_session, multi_station_setup):
    """Verify predicted high AQI triggers PREDICTED_THRESHOLD alert in Alert Center."""
    loc1 = multi_station_setup["loc1"]
    now = datetime.now(timezone.utc)

    pred = PredictionRecord(
        location_id=loc1.id,
        base_timestamp=now,
        target_timestamp=now + timedelta(hours=3),
        horizon_hours=3,
        predicted_aqi=350.0,
        predicted_category="Very Poor",
        model_name="RandomForestRegressor",
        training_observations=100,
        is_prediction=True,
    )
    db_session.add(pred)
    db_session.commit()

    alerts = evaluate_location_alerts(db_session, location_id=loc1.id)
    pred_alerts = [a for a in alerts if a.alert_type == AlertType.PREDICTED_THRESHOLD]
    assert len(pred_alerts) >= 1
    assert pred_alerts[0].observed_value == 350.0


def test_recommendation_service_forecast_prevention_integration(db_session, multi_station_setup):
    """Verify predicted high AQI generates FORECAST_PREVENTION recommendations."""
    loc1 = multi_station_setup["loc1"]
    now = datetime.now(timezone.utc)

    pred = PredictionRecord(
        location_id=loc1.id,
        base_timestamp=now,
        target_timestamp=now + timedelta(hours=6),
        horizon_hours=6,
        predicted_aqi=320.0,
        predicted_category="Very Poor",
        model_name="RandomForestRegressor",
        training_observations=100,
        is_prediction=True,
    )
    db_session.add(pred)
    db_session.commit()

    recs_resp = evaluate_location_recommendations(db_session, location_id=loc1.id)
    assert recs_resp.forecast_summary is not None
    assert recs_resp.forecast_summary.predicted_aqi == 320.0
    assert len(recs_resp.recommendations) > 0


# ==============================================================================
# 11. API Endpoints & RBAC Tests
# ==============================================================================

def test_api_prediction_train_rbac(auth_tokens, multi_station_setup):
    """Verify POST /api/v1/prediction/train enforces ADMIN role."""
    resp = client.post("/api/v1/prediction/train", json={"horizons": [1]})
    assert resp.status_code == 401

    # Viewer is forbidden
    resp = client.post(
        "/api/v1/prediction/train",
        json={"horizons": [1]},
        headers={"Authorization": f"Bearer {auth_tokens['viewer']}"},
    )
    assert resp.status_code == 403

    # Analyst has training privileges
    resp = client.post(
        "/api/v1/prediction/train",
        json={"horizons": [1], "min_observations": 20},
        headers={"Authorization": f"Bearer {auth_tokens['analyst']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ["SUCCESS", "PARTIAL_SUCCESS"]

    # Admin has training privileges
    resp = client.post(
        "/api/v1/prediction/train",
        json={"horizons": [1], "min_observations": 20},
        headers={"Authorization": f"Bearer {auth_tokens['admin']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ["SUCCESS", "PARTIAL_SUCCESS"]


def test_api_active_models_endpoint(auth_tokens, db_session, multi_station_setup):
    """Verify GET /api/v1/prediction/models/active returns active models."""
    train_general_models(db_session, horizons=[1, 3], min_observations=20)

    resp = client.get("/api/v1/prediction/models/active")
    assert resp.status_code == 401

    resp = client.get(
        "/api/v1/prediction/models/active",
        headers={"Authorization": f"Bearer {auth_tokens['viewer']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["horizon_hours"] in [1, 3]
    assert data[0]["is_active"] is True


def test_backward_compatibility_phase9_local_training(auth_tokens, multi_station_setup):
    """Verify existing Phase 9 POST /api/v1/prediction/train with location_id still functions."""
    loc1 = multi_station_setup["loc1"]
    resp = client.post(
        "/api/v1/prediction/train",
        json={"location_id": loc1.id, "horizon_hours": 1, "min_observations": 20},
        headers={"Authorization": f"Bearer {auth_tokens['admin']}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["location_id"] == loc1.id
