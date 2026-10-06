from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import AlertRule
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import ModelRegistryRecord, PredictionRecord
from backend.app.schemas.trust import (
    DataFreshnessStatus,
    PredictionReadiness,
    StationDataFreshness,
    StationDataQuality,
    StationDegradedState,
    StationPredictionTrust,
    StationProvenanceTrust,
    StationTrustResponse,
    SystemTrustOverview,
)
from backend.app.services.aqi_engine import AQIStatus, calculate_aqi
from backend.app.services.automation_service import get_automation_supervisor

SUPPORTED_POLLUTANTS = ["pm25", "pm10", "no2", "so2", "co", "o3"]


def evaluate_data_freshness(
    timestamp: Optional[datetime],
    now: Optional[datetime] = None,
) -> StationDataFreshness:
    """
    Deterministically evaluates observation freshness based on configured thresholds:
    - FRESH: age <= FRESHNESS_FRESH_THRESHOLD_HOURS (default 3.0h)
    - STALE: 3.0h < age <= FRESHNESS_STALE_THRESHOLD_HOURS (default 24.0h)
    - UNAVAILABLE: age > 24.0h or missing timestamp
    Timezone-safe calculation normalized to UTC.
    """
    if timestamp is None:
        return StationDataFreshness(
            status=DataFreshnessStatus.UNAVAILABLE,
            observation_timestamp=None,
            age_hours=None,
            age_minutes=None,
            message="UNAVAILABLE — No recent valid observation",
        )

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    ts = timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    diff_seconds = max(0.0, (now - ts).total_seconds())
    age_hours = round(diff_seconds / 3600.0, 2)
    age_minutes = round(diff_seconds / 60.0, 1)

    fresh_limit = settings.FRESHNESS_FRESH_THRESHOLD_HOURS
    stale_limit = settings.FRESHNESS_STALE_THRESHOLD_HOURS

    if age_hours <= fresh_limit:
        status = DataFreshnessStatus.FRESH
        if age_hours < 1.0:
            msg = f"FRESH — Observed {int(age_minutes)}m ago"
        else:
            msg = f"FRESH — Observed {age_hours:.1f}h ago"
    elif age_hours <= stale_limit:
        status = DataFreshnessStatus.STALE
        msg = f"STALE — Last observation {age_hours:.1f}h ago"
    else:
        status = DataFreshnessStatus.UNAVAILABLE
        msg = f"UNAVAILABLE — Data exceeds {int(stale_limit)}h freshness threshold ({age_hours:.1f}h old)"

    return StationDataFreshness(
        status=status,
        observation_timestamp=ts,
        age_hours=age_hours,
        age_minutes=age_minutes,
        message=msg,
    )


def evaluate_data_quality(
    reading: Optional[AirQualityReading],
    aqi_rec: Optional[AQIRecord] = None,
) -> StationDataQuality:
    """
    Lightweight data quality summary for the current station observation.
    Derives valid pollutant count, missing pollutants, pollutants used for CPCB NAQI,
    and completeness percentage without modifying Phase 4 calculation rules.
    """
    if reading is None:
        return StationDataQuality(
            aqi_valid=False,
            aqi_status="NO_DATA",
            pollutants_available=[],
            pollutants_missing=list(SUPPORTED_POLLUTANTS),
            pollutants_used_for_aqi=[],
            dominant_pollutant=None,
            total_pollutants_monitored=len(SUPPORTED_POLLUTANTS),
            available_count=0,
            completeness_pct=0.0,
            quality_status="INVALID",
            validation_notes="No observation recorded for this station.",
        )

    avail: List[str] = []
    missing: List[str] = []

    for p in SUPPORTED_POLLUTANTS:
        val = getattr(reading, p, None)
        if val is not None and not math.isnan(val) and not math.isinf(val):
            avail.append(p)
        else:
            missing.append(p)

    available_count = len(avail)
    completeness_pct = round((available_count / float(len(SUPPORTED_POLLUTANTS))) * 100.0, 1)

    # Derive AQI status and pollutants used
    aqi_valid = False
    aqi_status = "INSUFFICIENT_DATA"
    pollutants_used: List[str] = []
    dominant = None

    if aqi_rec and aqi_rec.status == "CALCULATED" and aqi_rec.aqi is not None:
        aqi_valid = True
        aqi_status = aqi_rec.status
        dominant = aqi_rec.dominant_pollutant
        if aqi_rec.pollutant_subindices and isinstance(aqi_rec.pollutant_subindices, dict):
            pollutants_used = [k for k, v in aqi_rec.pollutant_subindices.items() if v is not None]
    else:
        # Evaluate dynamically via Phase 4 engine
        calc = calculate_aqi(
            pm25=reading.pm25,
            pm10=reading.pm10,
            no2=reading.no2,
            so2=reading.so2,
            co=reading.co,
            o3=reading.o3,
            timestamp=reading.timestamp,
        )
        if calc.status == AQIStatus.CALCULATED and calc.aqi is not None:
            aqi_valid = True
            aqi_status = "CALCULATED"
            dominant = calc.dominant_pollutant
            if calc.sub_indices:
                pollutants_used = [k for k, v in calc.sub_indices.items() if v is not None]
        else:
            aqi_status = calc.status.value if hasattr(calc.status, "value") else str(calc.status)

    quality_status_str = (
        reading.quality_status.value
        if hasattr(reading.quality_status, "value")
        else str(reading.quality_status)
    )

    return StationDataQuality(
        aqi_valid=aqi_valid,
        aqi_status=aqi_status,
        pollutants_available=avail,
        pollutants_missing=missing,
        pollutants_used_for_aqi=pollutants_used,
        dominant_pollutant=dominant,
        total_pollutants_monitored=len(SUPPORTED_POLLUTANTS),
        available_count=available_count,
        completeness_pct=completeness_pct,
        quality_status=quality_status_str,
        validation_notes=reading.validation_notes,
    )


def evaluate_provenance(reading: Optional[AirQualityReading]) -> StationProvenanceTrust:
    """
    Transparently reports data source provenance without relabeling or misattribution.
    """
    if reading is None or not reading.source_type:
        return StationProvenanceTrust(
            source_type="UNKNOWN",
            source_name="Unknown Source",
            provider=None,
            notice="No physical telemetry or dataset associated with this query.",
        )

    st = (
        reading.source_type.value
        if hasattr(reading.source_type, "value")
        else str(reading.source_type)
    ).upper()

    notices = {
        "API": "Physical atmospheric telemetry ingested from official monitoring network API.",
        "SIMULATED": "100% Software-only synthetic telemetry with mathematical diurnal variation. Not an actual physical measurement.",
        "UPLOADED": "Static historical or external observational dataset uploaded into system.",
        "PREDICTED": "Statistical ML model forecast estimate based on atmospheric lag features.",
        "WHAT_IF": "Hypothetical simulated variation for impact scenario analysis.",
        "DEMO": "Demo seed dataset for development and visual demonstration.",
    }
    notice = notices.get(st, f"Data provenance recorded as {st}.")

    source_name = reading.data_source.name if reading.data_source else f"{st} Data"
    provider = reading.data_source.provider if reading.data_source else None

    return StationProvenanceTrust(
        source_type=st,
        source_name=source_name,
        provider=provider,
        notice=notice,
    )


def evaluate_prediction_trust(
    db: Session,
    location_id: int,
    now: Optional[datetime] = None,
) -> StationPredictionTrust:
    """
    Exposes deterministic prediction readiness/status for a station:
    - READY: Active model exists, >= 4 continuous hourly readings, fresh input.
    - INSUFFICIENT_HISTORY: < 4 continuous hourly readings available.
    - MODEL_UNAVAILABLE: No active model registered for forecasting.
    - STALE_INPUT: Model exists and >= 4 readings exist, but latest observation is delayed.
    """
    # 1. Check model registry
    active_models = (
        db.query(ModelRegistryRecord)
        .filter(ModelRegistryRecord.is_active == True)
        .order_by(ModelRegistryRecord.horizon_hours.asc())
        .all()
    )
    active_horizons = [m.horizon_hours for m in active_models]
    model_available = len(active_models) > 0

    # 2. Check local continuous history (requires >= 4 valid readings for lag features)
    recent_readings = (
        db.query(AirQualityReading)
        .filter(
            AirQualityReading.location_id == location_id,
            AirQualityReading.quality_status == QualityStatus.VALID,
        )
        .order_by(AirQualityReading.timestamp.desc())
        .limit(4)
        .all()
    )
    hourly_count = len(recent_readings)
    sufficient_history = hourly_count >= 4

    # 3. Check input freshness
    latest_reading_ts = recent_readings[0].timestamp if recent_readings else None
    freshness = evaluate_data_freshness(latest_reading_ts, now)
    is_stale_input = freshness.status in (DataFreshnessStatus.STALE, DataFreshnessStatus.UNAVAILABLE)

    # 4. Determine readiness state
    if not model_available:
        readiness = PredictionReadiness.MODEL_UNAVAILABLE
        reason = "No active ML model registry entries available for forecasting."
    elif not sufficient_history:
        readiness = PredictionReadiness.INSUFFICIENT_HISTORY
        reason = (
            f"Insufficient continuous hourly history: station has {hourly_count} valid reading(s); "
            "at least 4 continuous hourly observations are required to evaluate atmospheric lag features."
        )
    elif is_stale_input:
        readiness = PredictionReadiness.STALE_INPUT
        reason = (
            f"Trained model available and station has {hourly_count} history readings, "
            f"but latest observation is delayed ({freshness.message})."
        )
    else:
        readiness = PredictionReadiness.READY
        reason = (
            f"Active General Multi-Station Model suite ready across {len(active_horizons)} horizon(s) "
            "with fresh atmospheric input data."
        )

    # 5. Fetch latest persisted prediction record summary, if any
    latest_pred_rec = (
        db.query(PredictionRecord)
        .filter(PredictionRecord.location_id == location_id)
        .order_by(PredictionRecord.created_at.desc())
        .first()
    )
    pred_summary = None
    if latest_pred_rec:
        pred_summary = {
            "id": latest_pred_rec.id,
            "predicted_aqi": latest_pred_rec.predicted_aqi,
            "predicted_category": latest_pred_rec.predicted_category,
            "horizon_hours": latest_pred_rec.horizon_hours,
            "base_timestamp": latest_pred_rec.base_timestamp.isoformat() if latest_pred_rec.base_timestamp else None,
            "target_timestamp": latest_pred_rec.target_timestamp.isoformat() if latest_pred_rec.target_timestamp else None,
            "model_name": latest_pred_rec.model_name,
            "created_at": latest_pred_rec.created_at.isoformat() if latest_pred_rec.created_at else None,
            "is_prediction": True,
        }

    return StationPredictionTrust(
        readiness=readiness,
        sufficient_history=sufficient_history,
        continuous_hourly_count=hourly_count,
        model_available=model_available,
        active_horizons=active_horizons,
        reason=reason,
        latest_prediction=pred_summary,
    )


def evaluate_degraded_state(
    db: Session,
    location_id: int,
    ml_ready: bool = True,
) -> StationDegradedState:
    """
    Evaluates subsystem operational integrity without cascading failure:
    - OpenAQ upstream availability (supervisor backoff inspection)
    - ML readiness
    - Alert engine integrity
    - Recommendation engine integrity
    """
    supervisor = get_automation_supervisor()
    in_backoff = supervisor.is_in_backoff()
    openaq_accessible = not in_backoff

    # Check alert engine rules
    active_rules_count = db.query(AlertRule).filter(AlertRule.enabled == True).count()
    alerts_operational = active_rules_count > 0

    recommendations_operational = True  # Stateless deterministic rule engine
    notes: List[str] = []

    if in_backoff:
        backoff_until_str = supervisor.backoff_until.isoformat() if supervisor.backoff_until else "active"
        notes.append(f"Upstream OpenAQ API rate-limited; supervisor in backoff until {backoff_until_str}.")

    if not ml_ready:
        notes.append("ML forecasting unavailable for this station; historical analytics remain operational.")

    if not alerts_operational:
        notes.append("No active alert rules configured; automated alert evaluation inactive.")

    is_degraded = bool(notes)

    return StationDegradedState(
        is_degraded=is_degraded,
        openaq_accessible=openaq_accessible,
        ml_ready=ml_ready,
        alerts_operational=alerts_operational,
        recommendations_operational=recommendations_operational,
        notes=notes,
    )


def get_station_trust(
    db: Session,
    location_id: int,
    now: Optional[datetime] = None,
) -> StationTrustResponse:
    """
    Generates comprehensive, multi-dimensional trust, quality, freshness,
    provenance, and degradation profile for a specific monitoring station.
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise ValueError(f"Location with ID {location_id} not found.")

    if now is None:
        now = datetime.now(timezone.utc)

    # 1. Fetch latest observation
    latest_reading = (
        db.query(AirQualityReading)
        .filter(AirQualityReading.location_id == location_id)
        .order_by(AirQualityReading.timestamp.desc())
        .first()
    )

    # 2. Fetch latest AQI record
    latest_aqi_rec = None
    if latest_reading:
        latest_aqi_rec = (
            db.query(AQIRecord)
            .filter(AQIRecord.reading_id == latest_reading.id)
            .first()
        )

    # 3. Derive trust components
    freshness = evaluate_data_freshness(latest_reading.timestamp if latest_reading else None, now)
    quality = evaluate_data_quality(latest_reading, latest_aqi_rec)
    provenance = evaluate_provenance(latest_reading)
    prediction = evaluate_prediction_trust(db, location_id, now)
    degraded = evaluate_degraded_state(db, location_id, ml_ready=(prediction.readiness == PredictionReadiness.READY))

    # 4. Automation state
    supervisor = get_automation_supervisor()
    sup_status = supervisor.get_status(db)
    automation_dict = {
        "status": sup_status.status,
        "enabled": sup_status.enabled,
        "paused": sup_status.paused,
        "last_run": sup_status.last_run.isoformat() if sup_status.last_run else None,
        "next_run": sup_status.next_run.isoformat() if sup_status.next_run else None,
        "in_backoff": supervisor.is_in_backoff(),
    }

    current_aqi_val = latest_aqi_rec.aqi if latest_aqi_rec else None
    current_category_val = latest_aqi_rec.category if latest_aqi_rec else None

    return StationTrustResponse(
        location_id=location.id,
        location_name=location.name,
        city=location.city,
        state=location.state,
        country=location.country,
        external_provider=location.external_provider,
        external_id=location.external_id,
        is_active=location.is_active,
        current_aqi=current_aqi_val,
        aqi_category=current_category_val,
        freshness=freshness,
        quality=quality,
        provenance=provenance,
        prediction=prediction,
        automation=automation_dict,
        degraded_state=degraded,
        evaluated_at=now,
    )


def get_system_trust_overview(
    db: Session,
    now: Optional[datetime] = None,
) -> SystemTrustOverview:
    """
    Computes system-wide data freshness distribution, ML horizon readiness,
    automation supervisor state, and source breakdown across all registered stations.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    total_locations = db.query(Location).count()
    active_locations = db.query(Location).filter(Location.is_active == True).all()

    fresh_count = 0
    stale_count = 0
    unavailable_count = 0

    # Evaluate latest observation timestamp per active location
    for loc in active_locations:
        latest_reading = (
            db.query(AirQualityReading.timestamp)
            .filter(AirQualityReading.location_id == loc.id)
            .order_by(AirQualityReading.timestamp.desc())
            .first()
        )
        ts = latest_reading[0] if latest_reading else None
        f_eval = evaluate_data_freshness(ts, now)
        if f_eval.status == DataFreshnessStatus.FRESH:
            fresh_count += 1
        elif f_eval.status == DataFreshnessStatus.STALE:
            stale_count += 1
        else:
            unavailable_count += 1

    # Active model registry horizons
    active_models = (
        db.query(ModelRegistryRecord)
        .filter(ModelRegistryRecord.is_active == True)
        .order_by(ModelRegistryRecord.horizon_hours.asc())
        .all()
    )
    active_horizons = [m.horizon_hours for m in active_models]

    # Automation state
    supervisor = get_automation_supervisor()
    sup_status = supervisor.get_status(db)

    # Data sources breakdown
    source_counts_query = (
        db.query(AirQualityReading.source_type, func.count(AirQualityReading.id))
        .group_by(AirQualityReading.source_type)
        .all()
    )
    sources_summary: Dict[str, int] = {}
    for st, count in source_counts_query:
        st_key = st.value if hasattr(st, "value") else str(st)
        sources_summary[st_key] = count

    return SystemTrustOverview(
        total_locations=total_locations,
        active_locations=len(active_locations),
        fresh_stations_count=fresh_count,
        stale_stations_count=stale_count,
        unavailable_stations_count=unavailable_count,
        active_model_horizons=active_horizons,
        available_models_count=len(active_models),
        automation_status=sup_status.status,
        automation_running=(sup_status.status == "RUNNING"),
        automation_paused=sup_status.paused,
        last_sync=sup_status.last_run,
        next_sync=sup_status.next_run,
        data_sources_summary=sources_summary,
        evaluated_at=now,
    )
