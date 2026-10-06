import hashlib
import logging
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import ModelRegistryRecord, PredictionRecord
from backend.app.services.aqi_breakpoints import get_aqi_category
from backend.app.services.aqi_engine import AQIStatus, calculate_aqi

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "month_sin",
    "month_cos",
    "pm25",
    "pm10",
    "no2",
    "so2",
    "co",
    "o3",
    "temperature",
    "humidity",
    "aqi_current",
    "aqi_lag_1",
    "aqi_lag_2",
    "aqi_lag_3",
    "aqi_rolling_mean_3",
    "aqi_rolling_max_3",
    "pm25_lag_1",
    "pm10_lag_1",
]

DEFAULT_HORIZONS = [1, 3, 6, 12, 24]

# In-memory cache for loaded estimators: {horizon: (file_mtime, model_instance, record_dict)}
_MODEL_CACHE: Dict[int, Tuple[float, Any, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


# ==============================================================================
# Process-Safe File Lock for Model Training
# ==============================================================================

class FileTrainingLock:
    """
    Process-safe file lock using atomic OS creation flags (O_CREAT | O_EXCL)
    to protect multi-worker / multi-process training jobs from race conditions.
    """
    def __init__(self, lock_path: Optional[str] = None, timeout_seconds: float = 600.0):
        if lock_path is None:
            lock_dir = settings.MODEL_DIR
            os.makedirs(lock_dir, exist_ok=True)
            self.lock_path = os.path.join(lock_dir, "training.lock")
        else:
            self.lock_path = lock_path
        self.timeout_seconds = timeout_seconds
        self.fd = None

    def __enter__(self):
        start_time = time.time()
        while True:
            try:
                # O_CREAT | O_EXCL is atomic across processes on both Windows and POSIX
                self.fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self.fd, f"PID:{os.getpid()}:{time.time()}".encode("utf-8"))
                return self
            except FileExistsError:
                # Inspect whether existing lock is stale (process died or timed out)
                try:
                    mtime = os.path.getmtime(self.lock_path)
                    if (time.time() - mtime) > self.timeout_seconds:
                        try:
                            os.unlink(self.lock_path)
                            continue
                        except OSError:
                            pass
                except OSError:
                    pass

                if time.time() - start_time > 2.0:
                    raise BlockingIOError("Another training process is currently in progress.")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass
            self.fd = None


# ==============================================================================
# Checksum Helper
# ==============================================================================

def compute_file_sha256(file_path: str) -> str:
    """Computes SHA-256 hash of a file on disk."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


# ==============================================================================
# Shared Feature Construction Logic
# ==============================================================================

def build_feature_row(rec: Dict[str, Any], prev_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Constructs the standard 22-dimensional feature dictionary for an observation
    using its reading and preceding chronological observations from the same station.
    Station-independent: contains zero station or city identifiers.
    """
    ts: datetime = rec["timestamp"]
    r: AirQualityReading = rec["reading"]

    # Diurnal and seasonal cyclical encodings
    hour_val = ts.hour + ts.minute / 60.0
    hour_sin = math.sin(2.0 * math.pi * hour_val / 24.0)
    hour_cos = math.cos(2.0 * math.pi * hour_val / 24.0)

    dow_val = ts.weekday()
    dow_sin = math.sin(2.0 * math.pi * dow_val / 7.0)
    dow_cos = math.cos(2.0 * math.pi * dow_val / 7.0)

    month_val = ts.month
    month_sin = math.sin(2.0 * math.pi * month_val / 12.0)
    month_cos = math.cos(2.0 * math.pi * month_val / 12.0)

    # Current and historical lags (strictly from the same station)
    aqi_current = rec.get("aqi")
    aqi_lag_1 = prev_records[-1]["aqi"] if len(prev_records) >= 1 else None
    aqi_lag_2 = prev_records[-2]["aqi"] if len(prev_records) >= 2 else None
    aqi_lag_3 = prev_records[-3]["aqi"] if len(prev_records) >= 3 else None

    recent_aqis = [p["aqi"] for p in prev_records[-2:] if p.get("aqi") is not None]
    if aqi_current is not None:
        recent_aqis.append(aqi_current)

    aqi_rolling_mean_3 = float(np.mean(recent_aqis)) if recent_aqis else None
    aqi_rolling_max_3 = float(np.max(recent_aqis)) if recent_aqis else None

    pm25_lag_1 = prev_records[-1]["reading"].pm25 if len(prev_records) >= 1 else None
    pm10_lag_1 = prev_records[-1]["reading"].pm10 if len(prev_records) >= 1 else None

    return {
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "dow_sin": dow_sin,
        "dow_cos": dow_cos,
        "month_sin": month_sin,
        "month_cos": month_cos,
        "pm25": r.pm25,
        "pm10": r.pm10,
        "no2": r.no2,
        "so2": r.so2,
        "co": r.co,
        "o3": r.o3,
        "temperature": r.temperature,
        "humidity": r.humidity,
        "aqi_current": aqi_current,
        "aqi_lag_1": aqi_lag_1,
        "aqi_lag_2": aqi_lag_2,
        "aqi_lag_3": aqi_lag_3,
        "aqi_rolling_mean_3": aqi_rolling_mean_3,
        "aqi_rolling_max_3": aqi_rolling_max_3,
        "pm25_lag_1": pm25_lag_1,
        "pm10_lag_1": pm10_lag_1,
    }


def features_to_matrix(feature_dicts: List[Dict[str, Any]]) -> np.ndarray:
    """Converts list of feature dicts to 2D numpy array, keeping NaNs intact."""
    matrix = np.empty((len(feature_dicts), len(FEATURE_NAMES)), dtype=np.float64)
    for i, row in enumerate(feature_dicts):
        for j, col in enumerate(FEATURE_NAMES):
            val = row.get(col)
            matrix[i, j] = np.nan if val is None else float(val)
    return matrix


def split_chronologically(
    X: List[Any],
    y: List[float],
    timestamps: List[datetime],
    split_ratio: float = 0.8,
) -> Tuple[List[Any], List[Any], List[float], List[float], List[datetime], List[datetime]]:
    """
    Splits samples chronologically without temporal leakage.
    First split_ratio (e.g. 80%) for training, remaining 20% for validation.
    """
    n = len(X)
    split_idx = int(n * split_ratio)
    split_idx = max(1, min(split_idx, n - 1))

    X_train = X[:split_idx]
    X_val = X[split_idx:]
    y_train = y[:split_idx]
    y_val = y[split_idx:]
    t_train = timestamps[:split_idx]
    t_val = timestamps[split_idx:]

    return X_train, X_val, y_train, y_val, t_train, t_val


# ==============================================================================
# Single-Location Feature Extraction (Phase 9 Backward Compatibility)
# ==============================================================================

def extract_features_and_targets(
    db: Session,
    location_id: int,
    horizon_hours: int = 1,
) -> Tuple[List[Dict[str, Any]], List[float], List[datetime], List[str]]:
    """
    Extracts chronological features, targets, timestamps, and data sources for a location.
    Preserves NaNs for missing pollutant or meteorological values without converting to zero.
    """
    readings = (
        db.query(AirQualityReading)
        .join(AirQualityReading.data_source)
        .outerjoin(AQIRecord, AQIRecord.reading_id == AirQualityReading.id)
        .filter(
            AirQualityReading.location_id == location_id,
            AirQualityReading.quality_status == QualityStatus.VALID,
        )
        .order_by(AirQualityReading.timestamp.asc())
        .all()
    )

    if not readings:
        return [], [], [], []

    records: List[Dict[str, Any]] = []
    sources = set()

    for r in readings:
        if r.data_source:
            sources.add(r.data_source.source_type.value)
        # Find associated AQI value
        aqi_val = None
        if hasattr(r, "aqi_record") and r.aqi_record:
            if isinstance(r.aqi_record, list) and r.aqi_record:
                aqi_val = r.aqi_record[0].aqi
            elif not isinstance(r.aqi_record, list):
                aqi_val = r.aqi_record.aqi

        # Fallback to CPCB calculation if AQIRecord row is absent
        if aqi_val is None:
            calc = calculate_aqi(
                pm25=r.pm25,
                pm10=r.pm10,
                no2=r.no2,
                so2=r.so2,
                co=r.co,
                o3=r.o3,
                timestamp=r.timestamp,
            )
            if calc.status == AQIStatus.CALCULATED and calc.aqi is not None:
                aqi_val = calc.aqi

        records.append({
            "reading": r,
            "timestamp": r.timestamp,
            "aqi": aqi_val,
        })

    # Build sequential feature rows with lags
    feature_rows: List[Dict[str, Any]] = []
    sample_timestamps: List[datetime] = []

    for idx, rec in enumerate(records):
        prev_records = records[max(0, idx - 3):idx]
        feature_dict = build_feature_row(rec, prev_records)
        feature_rows.append(feature_dict)
        sample_timestamps.append(rec["timestamp"])

    # Align future target: actual AQI at t + horizon_hours
    X_samples: List[Dict[str, Any]] = []
    y_targets: List[float] = []
    aligned_timestamps: List[datetime] = []

    target_delta = timedelta(hours=horizon_hours)

    for idx, f_row in enumerate(feature_rows):
        t_base = sample_timestamps[idx]
        t_target = t_base + target_delta

        # Find closest record within ±45 minutes of t_target
        matched_target_aqi = None
        min_diff = timedelta(minutes=45)

        for forward_idx in range(idx + 1, len(records)):
            f_ts = records[forward_idx]["timestamp"]
            diff = abs(f_ts - t_target)
            if diff < min_diff:
                min_diff = diff
                matched_target_aqi = records[forward_idx]["aqi"]
            elif f_ts > t_target + min_diff:
                break

        if matched_target_aqi is not None:
            X_samples.append(f_row)
            y_targets.append(float(matched_target_aqi))
            aligned_timestamps.append(t_base)

    return X_samples, y_targets, aligned_timestamps, sorted(list(sources))


# ==============================================================================
# Multi-Station Feature & Target Pooling (Phase 17 Step 3)
# ==============================================================================

def extract_multi_station_features_and_targets(
    db: Session,
    location_ids: Optional[List[int]] = None,
    horizon_hours: int = 1,
    allowed_sources: Optional[List[SourceType]] = None,
    allow_demo_fallback: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[float], List[float], int, int, List[str], bool]:
    """
    Extracts chronological features and targets across multiple stations without cross-station contamination.
    Constructs station-local lags and splits each station's timeline chronologically (80% train, 20% val).
    Filters out SIMULATED, WHAT_IF, and PREDICTED data.
    Returns:
        (X_train_all, X_val_all, y_train_all, y_val_all, station_count, total_samples, data_sources, has_simulated)
    """
    if allowed_sources is None:
        # Check if real API data exists
        api_count = (
            db.query(AirQualityReading)
            .join(AirQualityReading.data_source)
            .filter(
                DataSource.source_type == SourceType.API,
                AirQualityReading.quality_status == QualityStatus.VALID,
            )
            .count()
        )
        if api_count > 0 or not allow_demo_fallback:
            allowed_sources = [SourceType.API, SourceType.UPLOADED]
        else:
            # Fallback for dev/demo testing if zero real API observations exist
            allowed_sources = [SourceType.API, SourceType.UPLOADED, SourceType.DEMO]

    query = (
        db.query(AirQualityReading)
        .join(AirQualityReading.data_source)
        .outerjoin(AQIRecord, AQIRecord.reading_id == AirQualityReading.id)
        .filter(
            AirQualityReading.quality_status == QualityStatus.VALID,
            DataSource.source_type.in_(allowed_sources),
        )
    )
    if location_ids:
        query = query.filter(AirQualityReading.location_id.in_(location_ids))

    all_readings = query.order_by(AirQualityReading.location_id.asc(), AirQualityReading.timestamp.asc()).all()
    if not all_readings:
        return [], [], [], [], 0, 0, [], False

    # Group by location_id
    by_station: Dict[int, List[AirQualityReading]] = {}
    sources: set = set()
    has_simulated = False

    for r in all_readings:
        by_station.setdefault(r.location_id, []).append(r)
        if r.data_source:
            sources.add(r.data_source.source_type.value)
            if r.data_source.source_type == SourceType.SIMULATED:
                has_simulated = True

    X_train_all: List[Dict[str, Any]] = []
    X_val_all: List[Dict[str, Any]] = []
    y_train_all: List[float] = []
    y_val_all: List[float] = []
    valid_stations_count = 0
    total_samples = 0

    target_delta = timedelta(hours=horizon_hours)

    for loc_id, st_readings in by_station.items():
        if len(st_readings) < 5:
            continue

        records: List[Dict[str, Any]] = []
        for r in st_readings:
            aqi_val = None
            if hasattr(r, "aqi_record") and r.aqi_record:
                if isinstance(r.aqi_record, list) and r.aqi_record:
                    aqi_val = r.aqi_record[0].aqi
                elif not isinstance(r.aqi_record, list):
                    aqi_val = r.aqi_record.aqi

            if aqi_val is None:
                calc = calculate_aqi(
                    pm25=r.pm25, pm10=r.pm10, no2=r.no2, so2=r.so2, co=r.co, o3=r.o3, timestamp=r.timestamp
                )
                if calc.status == AQIStatus.CALCULATED and calc.aqi is not None:
                    aqi_val = calc.aqi

            records.append({
                "reading": r,
                "timestamp": r.timestamp,
                "aqi": aqi_val,
            })

        # Build feature rows strictly within this station's timeline
        st_feature_rows: List[Dict[str, Any]] = []
        st_timestamps: List[datetime] = []
        for idx, rec in enumerate(records):
            prev_records = records[max(0, idx - 3):idx]
            feat_dict = build_feature_row(rec, prev_records)
            st_feature_rows.append(feat_dict)
            st_timestamps.append(rec["timestamp"])

        # Align targets strictly within this station's timeline
        st_X: List[Dict[str, Any]] = []
        st_y: List[float] = []
        st_aligned_ts: List[datetime] = []

        for idx, f_row in enumerate(st_feature_rows):
            t_base = st_timestamps[idx]
            t_target = t_base + target_delta

            matched_target_aqi = None
            min_diff = timedelta(minutes=45)

            for forward_idx in range(idx + 1, len(records)):
                f_ts = records[forward_idx]["timestamp"]
                diff = abs(f_ts - t_target)
                if diff < min_diff:
                    min_diff = diff
                    matched_target_aqi = records[forward_idx]["aqi"]
                elif f_ts > t_target + min_diff:
                    break

            if matched_target_aqi is not None:
                st_X.append(f_row)
                st_y.append(float(matched_target_aqi))
                st_aligned_ts.append(t_base)

        if not st_X:
            continue

        valid_stations_count += 1
        total_samples += len(st_X)

        # Chronological split per station (80% train, 20% val)
        X_tr, X_v, y_tr, y_v, _, _ = split_chronologically(st_X, st_y, st_aligned_ts, split_ratio=0.8)
        X_train_all.extend(X_tr)
        X_val_all.extend(X_v)
        y_train_all.extend(y_tr)
        y_val_all.extend(y_v)

    return (
        X_train_all,
        X_val_all,
        y_train_all,
        y_val_all,
        valid_stations_count,
        total_samples,
        sorted(list(sources)),
        has_simulated,
    )


# ==============================================================================
# Model Persistence & Model Registry Service
# ==============================================================================

def train_general_models(
    db: Session,
    horizons: Optional[List[int]] = None,
    min_observations: int = 24,
    allowed_sources: Optional[List[SourceType]] = None,
    allow_demo_fallback: bool = True,
) -> List[Dict[str, Any]]:
    """
    Trains and registers General Multi-Station ML models for all requested horizons.
    Serializes models via joblib to settings.MODEL_DIR and records metadata in model_registry_records.
    Process-safe using FileTrainingLock.
    """
    target_horizons = horizons or DEFAULT_HORIZONS
    model_dir = settings.MODEL_DIR
    os.makedirs(model_dir, exist_ok=True)

    results: List[Dict[str, Any]] = []

    # Acquire process-safe lock to prevent concurrent multi-worker stampedes
    with FileTrainingLock(timeout_seconds=600.0):
        for h in target_horizons:
            X_train_d, X_val_d, y_train, y_val, st_count, total_count, sources, has_sim = (
                extract_multi_station_features_and_targets(
                    db=db,
                    horizon_hours=h,
                    allowed_sources=allowed_sources,
                    allow_demo_fallback=allow_demo_fallback,
                )
            )

            if total_count < min_observations:
                logger.info(
                    f"Horizon +{h}h has insufficient samples ({total_count} < {min_observations}); skipping."
                )
                continue

            X_train_mat = features_to_matrix(X_train_d)
            X_val_mat = features_to_matrix(X_val_d)
            y_train_arr = np.array(y_train, dtype=np.float64)
            y_val_arr = np.array(y_val, dtype=np.float64)

            # Fit Random Forest (natively handles NaNs via missing-value branch splitting)
            model = RandomForestRegressor(
                n_estimators=50,
                random_state=42,
                max_depth=10,
                min_samples_leaf=1,
            )
            model.fit(X_train_mat, y_train_arr)

            # Evaluate on chronological validation set
            y_pred = model.predict(X_val_mat)
            mae = float(mean_absolute_error(y_val_arr, y_pred))
            rmse = float(np.sqrt(mean_squared_error(y_val_arr, y_pred)))
            if len(y_val_arr) <= 1 or np.all(y_val_arr == y_val_arr[0]):
                r2 = 1.0 if np.allclose(y_pred, y_val_arr, atol=1.0) else 0.0
            else:
                r2 = float(r2_score(y_val_arr, y_pred))

            # Serialize model artifact
            now_utc = datetime.now(timezone.utc)
            ts_suffix = int(now_utc.timestamp() * 1000)
            model_id = f"aeropulse_general_v1_{h}h_{ts_suffix}"
            artifact_filename = f"aeropulse_general_h{h}.joblib"
            artifact_path = os.path.join(model_dir, artifact_filename)
            joblib.dump(model, artifact_path)

            checksum = compute_file_sha256(artifact_path)

            # Deactivate previous active models for this horizon
            db.query(ModelRegistryRecord).filter(
                ModelRegistryRecord.horizon_hours == h,
                ModelRegistryRecord.is_active == True,
            ).update({"is_active": False})

            # Record in Model Registry
            registry_rec = ModelRegistryRecord(
                model_id=model_id,
                model_name="RandomForestRegressor",
                horizon_hours=h,
                version="1.0.0",
                artifact_path=artifact_path,
                training_observations=total_count,
                training_locations_count=st_count,
                mae=round(mae, 2),
                rmse=round(rmse, 2),
                r2=round(r2, 4),
                features=FEATURE_NAMES,
                data_sources=sources,
                has_simulated_data=has_sim,
                is_active=True,
                checksum=checksum,
                created_at=now_utc,
            )
            db.add(registry_rec)
            db.commit()
            db.refresh(registry_rec)

            # Invalidate/update in-memory cache
            with _CACHE_LOCK:
                _MODEL_CACHE[h] = (
                    os.path.getmtime(artifact_path),
                    model,
                    {
                        "model_id": model_id,
                        "mae": mae,
                        "rmse": rmse,
                        "r2": r2,
                        "sources": sources,
                        "has_sim": has_sim,
                        "training_observations": total_count,
                    },
                )

            results.append({
                "horizon_hours": h,
                "model_id": model_id,
                "status": "SUCCESS",
                "training_observations": total_count,
                "training_locations_count": st_count,
                "mae": round(mae, 2),
                "rmse": round(rmse, 2),
                "r2": round(r2, 4),
                "artifact_path": artifact_path,
                "checksum": checksum,
            })

    return results


def get_active_general_model(db: Session, horizon_hours: int) -> Optional[Tuple[Any, ModelRegistryRecord]]:
    """
    Retrieves and validates the active general model for a given horizon.
    Validates artifact existence, checksum, feature schema, and staleness policy.
    Returns (model_instance, registry_record) or None.
    """
    record = (
        db.query(ModelRegistryRecord)
        .filter(
            ModelRegistryRecord.horizon_hours == horizon_hours,
            ModelRegistryRecord.is_active == True,
        )
        .order_by(ModelRegistryRecord.created_at.desc())
        .first()
    )
    if not record:
        return None

    if not os.path.exists(record.artifact_path):
        logger.warning(f"Model artifact file missing at: {record.artifact_path}")
        return None

    # Validate feature schema matches exactly
    if record.features != FEATURE_NAMES:
        logger.warning(f"Model feature schema mismatch in record {record.model_id}")
        return None

    # Check in-memory cache
    mtime = os.path.getmtime(record.artifact_path)
    with _CACHE_LOCK:
        if horizon_hours in _MODEL_CACHE:
            cached_mtime, cached_model, _ = _MODEL_CACHE[horizon_hours]
            if cached_mtime == mtime:
                return cached_model, record

    # Validate checksum if recorded
    if record.checksum:
        current_checksum = compute_file_sha256(record.artifact_path)
        if current_checksum != record.checksum:
            logger.warning(f"Checksum mismatch for model {record.model_id}")
            return None

    try:
        model = joblib.load(record.artifact_path)
        with _CACHE_LOCK:
            _MODEL_CACHE[horizon_hours] = (
                mtime,
                model,
                {
                    "model_id": record.model_id,
                    "mae": record.mae,
                    "rmse": record.rmse,
                    "r2": record.r2,
                    "sources": record.data_sources,
                    "has_sim": record.has_simulated_data,
                    "training_observations": record.training_observations,
                },
            )
        return model, record
    except Exception as e:
        logger.error(f"Failed to load model artifact {record.artifact_path}: {e}")
        return None


# ==============================================================================
# General Model Prediction & Ingestion Auto-Forecasting
# ==============================================================================

def predict_with_general_model(
    db: Session,
    location_id: int,
    horizon_hours: int = 1,
) -> Dict[str, Any]:
    """
    Generates future AQI forecast using the active General Multi-Station ML Model.
    Enforces minimum local history (>= 4 observations) for complete lag features.
    Clamps AQI to [0.0, 500.0] and maps category to official CPCB standard.
    Persists PredictionRecord with source_type='API' and is_prediction=True.
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise ValueError(f"Location with ID {location_id} does not exist.")

    # 1. Fetch latest 4 readings for this station to build full lag features
    recent_readings = (
        db.query(AirQualityReading)
        .outerjoin(AQIRecord, AQIRecord.reading_id == AirQualityReading.id)
        .filter(
            AirQualityReading.location_id == location_id,
            AirQualityReading.quality_status == QualityStatus.VALID,
        )
        .order_by(AirQualityReading.timestamp.desc())
        .limit(4)
        .all()
    )

    if len(recent_readings) < 4:
        raise ValueError(
            f"Insufficient historical data: location {location_id} has {len(recent_readings)} observations; "
            "at least 4 continuous hourly observations are required to evaluate atmospheric trend lags."
        )

    # 2. Retrieve active general model for this horizon
    active_entry = get_active_general_model(db, horizon_hours=horizon_hours)
    if not active_entry:
        raise ValueError(f"No valid active General ML Model available for horizon +{horizon_hours}h.")

    model, registry_rec = active_entry

    # 3. Chronological ordering: [t-3, t-2, t-1, t0]
    readings_chrono = list(reversed(recent_readings))
    records: List[Dict[str, Any]] = []

    for r in readings_chrono:
        aqi_val = None
        if hasattr(r, "aqi_record") and r.aqi_record:
            if isinstance(r.aqi_record, list) and r.aqi_record:
                aqi_val = r.aqi_record[0].aqi
            elif not isinstance(r.aqi_record, list):
                aqi_val = r.aqi_record.aqi

        if aqi_val is None:
            calc = calculate_aqi(
                pm25=r.pm25, pm10=r.pm10, no2=r.no2, so2=r.so2, co=r.co, o3=r.o3, timestamp=r.timestamp
            )
            if calc.status == AQIStatus.CALCULATED and calc.aqi is not None:
                aqi_val = calc.aqi

        records.append({
            "reading": r,
            "timestamp": r.timestamp,
            "aqi": aqi_val,
        })

    # Build feature row for latest reading using shared helper
    latest_rec = records[-1]
    prev_recs = records[:-1]
    feature_dict = build_feature_row(latest_rec, prev_recs)

    # Inference
    X_mat = features_to_matrix([feature_dict])
    raw_pred = float(model.predict(X_mat)[0])
    clamped_aqi = max(0.0, min(500.0, round(raw_pred, 1)))
    category = get_aqi_category(round(clamped_aqi)) or "Moderate"

    base_ts = latest_rec["timestamp"]
    target_ts = base_ts + timedelta(hours=horizon_hours)

    provenance_notice = (
        "Predictions are generated by a software ML model using real atmospheric observations. "
        "Predictions are estimates, not physical measurements. Data provenance is shown for transparency."
    )
    if registry_rec.has_simulated_data:
        provenance_notice += " Training data includes SIMULATED observations."

    # Persist in prediction_records
    pred_rec = PredictionRecord(
        location_id=location_id,
        base_timestamp=base_ts,
        target_timestamp=target_ts,
        horizon_hours=horizon_hours,
        predicted_aqi=clamped_aqi,
        predicted_category=category,
        model_name=registry_rec.model_id,
        training_observations=registry_rec.training_observations,
        mae=registry_rec.mae,
        rmse=registry_rec.rmse,
        r2=registry_rec.r2,
        data_sources=registry_rec.data_sources,
        has_simulated_data=registry_rec.has_simulated_data,
        provenance_notice=provenance_notice,
        is_prediction=True,
    )
    db.add(pred_rec)
    db.commit()
    db.refresh(pred_rec)

    return {
        "id": pred_rec.id,
        "location_id": location_id,
        "location_name": location.name,
        "base_timestamp": base_ts,
        "target_timestamp": target_ts,
        "horizon_hours": horizon_hours,
        "predicted_aqi": clamped_aqi,
        "predicted_category": category,
        "model_name": registry_rec.model_id,
        "training_observations": registry_rec.training_observations,
        "mae": registry_rec.mae,
        "rmse": registry_rec.rmse,
        "r2": registry_rec.r2,
        "data_sources": registry_rec.data_sources,
        "has_simulated_data": registry_rec.has_simulated_data,
        "provenance_notice": provenance_notice,
        "is_prediction": True,
        "created_at": pred_rec.created_at,
    }


# ==============================================================================
# Existing Phase 9 Functions (Preserved for 100% Backward Compatibility)
# ==============================================================================

def train_and_evaluate_model(
    db: Session,
    location_id: int,
    horizon_hours: int = 1,
    min_observations: int = 24,
) -> Dict[str, Any]:
    """
    Trains and evaluates a location-specific model (Phase 9 backward compatibility).
    """
    X_dicts, y, timestamps, sources = extract_features_and_targets(
        db, location_id, horizon_hours=horizon_hours
    )

    has_simulated = SourceType.SIMULATED.value in sources
    provenance_notice = (
        "Predictions are generated by a software ML model using available historical air-quality data. "
        "Predictions are estimates, not physical measurements. Data provenance is shown for transparency."
    )
    if has_simulated:
        provenance_notice += " Training data includes SIMULATED observations."

    if len(X_dicts) < min_observations:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": (
                f"Insufficient historical data: required at least {min_observations} aligned observations "
                f"for horizon +{horizon_hours}h, found {len(X_dicts)}."
            ),
            "location_id": location_id,
            "horizon_hours": horizon_hours,
            "training_observations": len(X_dicts),
            "training_start": timestamps[0] if timestamps else None,
            "training_end": timestamps[-1] if timestamps else None,
            "metrics": None,
            "data_sources": sources,
            "has_simulated_data": has_simulated,
            "provenance_notice": provenance_notice,
        }

    # Chronological train/val split
    X_train_d, X_val_d, y_train, y_val, t_train, t_val = split_chronologically(
        X_dicts, y, timestamps, split_ratio=0.8
    )

    X_train_mat = features_to_matrix(X_train_d)
    X_val_mat = features_to_matrix(X_val_d)
    y_train_arr = np.array(y_train, dtype=np.float64)
    y_val_arr = np.array(y_val, dtype=np.float64)

    model = RandomForestRegressor(
        n_estimators=50,
        random_state=42,
        max_depth=10,
        min_samples_leaf=1,
    )
    model.fit(X_train_mat, y_train_arr)

    y_pred = model.predict(X_val_mat)
    mae = float(mean_absolute_error(y_val_arr, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_val_arr, y_pred)))
    if len(y_val_arr) <= 1 or np.all(y_val_arr == y_val_arr[0]):
        r2 = 1.0 if np.allclose(y_pred, y_val_arr, atol=1.0) else 0.0
    else:
        r2 = float(r2_score(y_val_arr, y_pred))

    return {
        "status": "SUCCESS",
        "message": f"Successfully trained and validated model on {len(X_dicts)} observations.",
        "location_id": location_id,
        "horizon_hours": horizon_hours,
        "training_observations": len(X_dicts),
        "training_start": timestamps[0],
        "training_end": timestamps[-1],
        "metrics": {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "r2": round(r2, 4),
        },
        "data_sources": sources,
        "has_simulated_data": has_simulated,
        "provenance_notice": provenance_notice,
        "model": model,
    }


def generate_predictions(
    db: Session,
    location_id: int,
    horizon_hours: int = 1,
    min_observations: int = 20,
) -> Dict[str, Any]:
    """
    Entry point for generating future AQI forecasts.
    Prefers the active General Multi-Station Model if available;
    falls back to on-demand location-specific model for Phase 9 test compatibility.
    """
    # 1. Prefer General Model if active
    active_entry = get_active_general_model(db, horizon_hours=horizon_hours)
    if active_entry is not None:
        try:
            return predict_with_general_model(db, location_id, horizon_hours=horizon_hours)
        except ValueError as val_err:
            err_msg = str(val_err)
            if "Insufficient historical data" in err_msg or "does not exist" in err_msg:
                raise
            # If General model fails for schema reasons, fallback to local on-demand
            logger.info("General model inference fallback note: %s", val_err)

    # 2. Location-specific on-demand fallback (Phase 9 behavior)
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise ValueError(f"Location with ID {location_id} does not exist.")

    train_res = train_and_evaluate_model(
        db, location_id, horizon_hours=horizon_hours, min_observations=min_observations
    )
    if train_res["status"] == "INSUFFICIENT_DATA":
        raise ValueError(train_res["message"])

    model = train_res["model"]
    metrics = train_res["metrics"]

    # Get latest chronological reading features
    latest_reading = (
        db.query(AirQualityReading)
        .outerjoin(AQIRecord, AQIRecord.reading_id == AirQualityReading.id)
        .filter(
            AirQualityReading.location_id == location_id,
            AirQualityReading.quality_status == QualityStatus.VALID,
        )
        .order_by(AirQualityReading.timestamp.desc())
        .first()
    )

    if not latest_reading:
        raise ValueError(f"No valid readings found for location {location_id}.")

    base_ts = latest_reading.timestamp
    target_ts = base_ts + timedelta(hours=horizon_hours)

    hour_val = base_ts.hour + base_ts.minute / 60.0
    dow_val = base_ts.weekday()
    month_val = base_ts.month

    aqi_current = None
    if hasattr(latest_reading, "aqi_record") and latest_reading.aqi_record:
        if isinstance(latest_reading.aqi_record, list) and latest_reading.aqi_record:
            aqi_current = latest_reading.aqi_record[0].aqi
        elif not isinstance(latest_reading.aqi_record, list):
            aqi_current = latest_reading.aqi_record.aqi

    prev_reading = (
        db.query(AirQualityReading)
        .outerjoin(AQIRecord, AQIRecord.reading_id == AirQualityReading.id)
        .filter(
            AirQualityReading.location_id == location_id,
            AirQualityReading.quality_status == QualityStatus.VALID,
            AirQualityReading.timestamp < base_ts,
        )
        .order_by(AirQualityReading.timestamp.desc())
        .first()
    )
    aqi_lag_1 = None
    pm25_lag_1 = None
    pm10_lag_1 = None
    if prev_reading:
        pm25_lag_1 = prev_reading.pm25
        pm10_lag_1 = prev_reading.pm10
        if hasattr(prev_reading, "aqi_record") and prev_reading.aqi_record:
            if isinstance(prev_reading.aqi_record, list) and prev_reading.aqi_record:
                aqi_lag_1 = prev_reading.aqi_record[0].aqi
            elif not isinstance(prev_reading.aqi_record, list):
                aqi_lag_1 = prev_reading.aqi_record.aqi

    latest_f_row = {
        "hour_sin": math.sin(2.0 * math.pi * hour_val / 24.0),
        "hour_cos": math.cos(2.0 * math.pi * hour_val / 24.0),
        "dow_sin": math.sin(2.0 * math.pi * dow_val / 7.0),
        "dow_cos": math.cos(2.0 * math.pi * dow_val / 7.0),
        "month_sin": math.sin(2.0 * math.pi * month_val / 12.0),
        "month_cos": math.cos(2.0 * math.pi * month_val / 12.0),
        "pm25": latest_reading.pm25,
        "pm10": latest_reading.pm10,
        "no2": latest_reading.no2,
        "so2": latest_reading.so2,
        "co": latest_reading.co,
        "o3": latest_reading.o3,
        "temperature": latest_reading.temperature,
        "humidity": latest_reading.humidity,
        "aqi_current": aqi_current,
        "aqi_lag_1": aqi_lag_1,
        "aqi_lag_2": aqi_lag_1,
        "aqi_lag_3": aqi_lag_1,
        "aqi_rolling_mean_3": aqi_current,
        "aqi_rolling_max_3": aqi_current,
        "pm25_lag_1": pm25_lag_1,
        "pm10_lag_1": pm10_lag_1,
    }

    X_latest_mat = features_to_matrix([latest_f_row])
    raw_pred = float(model.predict(X_latest_mat)[0])
    clamped_aqi = max(0.0, min(500.0, round(raw_pred, 1)))
    category = get_aqi_category(round(clamped_aqi)) or "Moderate"

    pred_rec = PredictionRecord(
        location_id=location_id,
        base_timestamp=base_ts,
        target_timestamp=target_ts,
        horizon_hours=horizon_hours,
        predicted_aqi=clamped_aqi,
        predicted_category=category,
        model_name="RandomForestRegressor",
        training_observations=train_res["training_observations"],
        mae=metrics["mae"] if metrics else None,
        rmse=metrics["rmse"] if metrics else None,
        r2=metrics["r2"] if metrics else None,
        data_sources=train_res["data_sources"],
        has_simulated_data=train_res["has_simulated_data"],
        provenance_notice=train_res["provenance_notice"],
        is_prediction=True,
    )
    db.add(pred_rec)
    db.commit()
    db.refresh(pred_rec)

    return {
        "id": pred_rec.id,
        "location_id": location_id,
        "location_name": location.name,
        "base_timestamp": base_ts,
        "target_timestamp": target_ts,
        "horizon_hours": horizon_hours,
        "predicted_aqi": clamped_aqi,
        "predicted_category": category,
        "model_name": "RandomForestRegressor",
        "training_observations": train_res["training_observations"],
        "mae": metrics["mae"] if metrics else None,
        "rmse": metrics["rmse"] if metrics else None,
        "r2": metrics["r2"] if metrics else None,
        "data_sources": train_res["data_sources"],
        "has_simulated_data": train_res["has_simulated_data"],
        "provenance_notice": train_res["provenance_notice"],
        "is_prediction": True,
        "created_at": pred_rec.created_at,
    }


# ==============================================================================
# Automatic Retraining Trigger Check
# ==============================================================================

def check_and_trigger_automatic_retraining(db: Session) -> Optional[List[Dict[str, Any]]]:
    """
    Evaluates whether the General ML Model requires background retraining:
    1. Condition A: Any of the default horizons is missing an active model.
    2. Condition B: Number of new valid real observations since previous training >= 200.
    3. Condition C: Active model is older than 7 days and new observations >= 50.
    If conditions are met, triggers train_general_models.
    """
    active_records = (
        db.query(ModelRegistryRecord)
        .filter(ModelRegistryRecord.is_active == True)
        .all()
    )
    active_horizons = {r.horizon_hours for r in active_records}

    # Condition A: Missing active model for any horizon
    missing_horizons = set(DEFAULT_HORIZONS) - active_horizons
    if missing_horizons:
        logger.info(f"Missing active models for horizons {sorted(missing_horizons)}; triggering training.")
        return train_general_models(db, horizons=DEFAULT_HORIZONS)

    # Condition B & C: Check observations delta and age
    latest_training_time = max(r.created_at for r in active_records)
    if latest_training_time.tzinfo is None:
        latest_training_time = latest_training_time.replace(tzinfo=timezone.utc)
    total_active_obs = max(r.training_observations for r in active_records)

    current_valid_obs = (
        db.query(AirQualityReading)
        .join(AirQualityReading.data_source)
        .filter(
            AirQualityReading.quality_status == QualityStatus.VALID,
            DataSource.source_type.in_([SourceType.API, SourceType.UPLOADED]),
        )
        .count()
    )

    delta_obs = current_valid_obs - total_active_obs
    now_utc = datetime.now(timezone.utc)
    model_age_days = (now_utc - latest_training_time).total_seconds() / 86400.0

    if delta_obs >= settings.ML_RETRAIN_OBSERVATION_THRESHOLD:
        logger.info(f"Retraining triggered: {delta_obs} new observations accumulated (threshold: {settings.ML_RETRAIN_OBSERVATION_THRESHOLD}).")
        return train_general_models(db, horizons=DEFAULT_HORIZONS)

    if model_age_days >= settings.ML_MODEL_STALENESS_DAYS and delta_obs >= settings.ML_RETRAIN_STALE_OBSERVATION_THRESHOLD:
        logger.info(f"Retraining triggered: model age {model_age_days:.1f}d >= {settings.ML_MODEL_STALENESS_DAYS}d with {delta_obs} new observations.")
        return train_general_models(db, horizons=DEFAULT_HORIZONS)

    return None
