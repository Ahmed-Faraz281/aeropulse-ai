from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from backend.app.models.aqi import AQIRecord
from backend.app.models.location import Location
from backend.app.models.prediction import PredictionRecord


DEFAULT_RULES = [
    {
        "name": "Poor AQI Exceedance",
        "alert_type": AlertType.AQI_THRESHOLD,
        "threshold": 201.0,
        "severity": AlertSeverity.HIGH,
        "enabled": True,
    },
    {
        "name": "Severe AQI Critical",
        "alert_type": AlertType.AQI_THRESHOLD,
        "threshold": 401.0,
        "severity": AlertSeverity.CRITICAL,
        "enabled": True,
    },
    {
        "name": "Sustained Elevated Pollution",
        "alert_type": AlertType.SUSTAINED_HIGH_AQI,
        "threshold": 201.0,
        "duration_hours": 2.0,
        "severity": AlertSeverity.HIGH,
        "enabled": True,
    },
    {
        "name": "Rapid AQI Surge",
        "alert_type": AlertType.RAPID_INCREASE,
        "threshold": 50.0,
        "window_hours": 2.0,
        "severity": AlertSeverity.WARNING,
        "enabled": True,
    },
    {
        "name": "Predicted Severe AQI Deterioration",
        "alert_type": AlertType.PREDICTED_THRESHOLD,
        "threshold": 201.0,
        "applies_to_prediction": True,
        "prediction_horizon_hours": 3,
        "severity": AlertSeverity.HIGH,
        "enabled": True,
    },
    {
        "name": "CPCB Category Deterioration",
        "alert_type": AlertType.CATEGORY_CHANGE,
        "threshold": 101.0,
        "severity": AlertSeverity.WARNING,
        "enabled": True,
    },
]


def ensure_default_alert_rules(db: Session) -> List[AlertRule]:
    """Ensures standard default alert rules exist in the database."""
    existing_count = db.query(AlertRule).count()
    if existing_count > 0:
        return db.query(AlertRule).all()

    created_rules = []
    for r in DEFAULT_RULES:
        rule = AlertRule(**r)
        db.add(rule)
        created_rules.append(rule)

    db.commit()
    for rule in created_rules:
        db.refresh(rule)
    return created_rules


def _get_or_create_alert(
    db: Session,
    location_id: int,
    rule_id: Optional[int],
    alert_type: AlertType,
    severity: AlertSeverity,
    title: str,
    message: str,
    observed_value: Optional[float],
    threshold_value: float,
    detected_at: datetime,
    source_type: str = "API",
    is_prediction: bool = False,
    prediction_id: Optional[int] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> Tuple[Alert, bool]:
    """
    Suppresses duplicate alerts for the same active condition.
    If an ACTIVE or ACKNOWLEDGED alert exists for (location_id, rule_id, alert_type),
    updates observed_value and detected_at without creating a duplicate.
    Returns (alert, created: bool).
    """
    existing = (
        db.query(Alert)
        .filter(
            Alert.location_id == location_id,
            Alert.rule_id == rule_id,
            Alert.alert_type == alert_type,
            Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]),
        )
        .first()
    )

    if existing:
        existing.observed_value = observed_value
        existing.detected_at = detected_at
        existing.message = message
        db.commit()
        db.refresh(existing)
        return existing, False

    new_alert = Alert(
        location_id=location_id,
        rule_id=rule_id,
        alert_type=alert_type,
        severity=severity,
        status=AlertStatus.ACTIVE,
        title=title,
        message=message,
        observed_value=observed_value,
        threshold_value=threshold_value,
        detected_at=detected_at,
        source_type=source_type,
        is_prediction=is_prediction,
        prediction_id=prediction_id,
        metadata_json=metadata_json,
    )
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)
    return new_alert, True


def evaluate_location_alerts(db: Session, location_id: int) -> List[Alert]:
    """
    Evaluates all enabled alert rules against current, historical, and predicted data
    for a monitored location. Handles duplicate suppression and automatic resolution.
    """
    # Verify location exists
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise ValueError(f"Location {location_id} not found.")

    # Ensure default rules exist
    ensure_default_alert_rules(db)
    rules = db.query(AlertRule).filter(AlertRule.enabled == True).all()
    if not rules:
        return []

    # Fetch recent readings with AQI records, ordered chronologically ascending
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

    triggered_alerts: List[Alert] = []

    # If no valid readings, skip observation rules
    latest_reading: Optional[AirQualityReading] = readings[-1] if readings else None
    latest_aqi_val: Optional[int] = None
    latest_category: Optional[str] = None
    source_type_str = "API"

    if latest_reading:
        source_type_str = latest_reading.source_type.value if latest_reading.source_type else "API"
        if hasattr(latest_reading, "aqi_record") and latest_reading.aqi_record:
            if isinstance(latest_reading.aqi_record, list) and latest_reading.aqi_record:
                latest_aqi_val = latest_reading.aqi_record[0].aqi
                latest_category = latest_reading.aqi_record[0].category
            elif not isinstance(latest_reading.aqi_record, list):
                latest_aqi_val = latest_reading.aqi_record.aqi
                latest_category = latest_reading.aqi_record.category

    # Pre-extract list of (timestamp, aqi, category) for time series evaluations
    ts_aqi_series = []
    for r in readings:
        aqi_v = None
        cat_v = None
        if hasattr(r, "aqi_record") and r.aqi_record:
            if isinstance(r.aqi_record, list) and r.aqi_record:
                aqi_v = r.aqi_record[0].aqi
                cat_v = r.aqi_record[0].category
            elif not isinstance(r.aqi_record, list):
                aqi_v = r.aqi_record.aqi
                cat_v = r.aqi_record.category
        if aqi_v is not None:
            ts_aqi_series.append({
                "timestamp": r.timestamp,
                "aqi": aqi_v,
                "category": cat_v,
                "reading": r,
            })

    # Evaluate each enabled rule
    for rule in rules:
        # A. AQI_THRESHOLD Rule
        if rule.alert_type == AlertType.AQI_THRESHOLD and not rule.applies_to_prediction:
            if latest_aqi_val is not None:
                if latest_aqi_val >= rule.threshold:
                    msg = (
                        f"AQI at {location.name} is {latest_aqi_val}, "
                        f"crossing the configured threshold of {int(rule.threshold)}."
                    )
                    alt, _ = _get_or_create_alert(
                        db=db,
                        location_id=location_id,
                        rule_id=rule.id,
                        alert_type=AlertType.AQI_THRESHOLD,
                        severity=rule.severity,
                        title=f"{rule.name} Triggered",
                        message=msg,
                        observed_value=float(latest_aqi_val),
                        threshold_value=rule.threshold,
                        detected_at=latest_reading.timestamp if latest_reading else datetime.now(timezone.utc),
                        source_type=source_type_str,
                        metadata_json={"category": latest_category},
                    )
                    triggered_alerts.append(alt)
                else:
                    # Auto-resolve if current AQI is now below threshold
                    active_alt = (
                        db.query(Alert)
                        .filter(
                            Alert.location_id == location_id,
                            Alert.rule_id == rule.id,
                            Alert.alert_type == AlertType.AQI_THRESHOLD,
                            Alert.status == AlertStatus.ACTIVE,
                        )
                        .first()
                    )
                    if active_alt:
                        active_alt.status = AlertStatus.RESOLVED
                        active_alt.resolved_at = datetime.now(timezone.utc)
                        db.commit()

        # B. SUSTAINED_HIGH_AQI Rule
        elif rule.alert_type == AlertType.SUSTAINED_HIGH_AQI:
            required_hours = rule.duration_hours or 2.0
            if ts_aqi_series:
                # Count consecutive readings at end of series meeting threshold
                consecutive_count = 0
                for item in reversed(ts_aqi_series):
                    if item["aqi"] >= rule.threshold:
                        consecutive_count += 1
                    else:
                        break

                # If duration in hours reached (assuming ~hourly intervals or timestamp difference)
                if consecutive_count >= required_hours:
                    msg = (
                        f"Sustained elevated AQI at {location.name} remained at or above {int(rule.threshold)} "
                        f"for the configured {required_hours:.1f}-hour duration (observed {latest_aqi_val})."
                    )
                    alt, _ = _get_or_create_alert(
                        db=db,
                        location_id=location_id,
                        rule_id=rule.id,
                        alert_type=AlertType.SUSTAINED_HIGH_AQI,
                        severity=rule.severity,
                        title=f"{rule.name}",
                        message=msg,
                        observed_value=float(latest_aqi_val) if latest_aqi_val is not None else rule.threshold,
                        threshold_value=rule.threshold,
                        detected_at=latest_reading.timestamp if latest_reading else datetime.now(timezone.utc),
                        source_type=source_type_str,
                        metadata_json={"duration_hours": float(consecutive_count)},
                    )
                    triggered_alerts.append(alt)

        # C. RAPID_INCREASE Rule
        elif rule.alert_type == AlertType.RAPID_INCREASE:
            window_hours = rule.window_hours or 2.0
            if len(ts_aqi_series) >= 2 and latest_reading:
                cutoff_time = latest_reading.timestamp - timedelta(hours=window_hours)
                # Find earliest reading within the window
                earlier = [item for item in ts_aqi_series if item["timestamp"] >= cutoff_time]
                if earlier and latest_aqi_val is not None:
                    min_aqi_in_window = min(item["aqi"] for item in earlier)
                    delta = latest_aqi_val - min_aqi_in_window
                    if delta >= rule.threshold:
                        msg = (
                            f"AQI increased by {int(delta)} points within the configured "
                            f"{window_hours:.1f}-hour window at {location.name}."
                        )
                        alt, _ = _get_or_create_alert(
                            db=db,
                            location_id=location_id,
                            rule_id=rule.id,
                            alert_type=AlertType.RAPID_INCREASE,
                            severity=rule.severity,
                            title=f"{rule.name}",
                            message=msg,
                            observed_value=float(delta),
                            threshold_value=rule.threshold,
                            detected_at=latest_reading.timestamp,
                            source_type=source_type_str,
                            metadata_json={"aqi_delta": float(delta), "window_hours": window_hours},
                        )
                        triggered_alerts.append(alt)

        # D. PREDICTED_THRESHOLD Rule
        elif rule.alert_type == AlertType.PREDICTED_THRESHOLD or rule.applies_to_prediction:
            pred_query = db.query(PredictionRecord).filter(PredictionRecord.location_id == location_id)
            if rule.prediction_horizon_hours:
                pred_query = pred_query.filter(PredictionRecord.horizon_hours == rule.prediction_horizon_hours)
            pred = pred_query.order_by(PredictionRecord.created_at.desc()).first()

            if pred and pred.predicted_aqi >= rule.threshold:
                source_label = "SIMULATED" if pred.has_simulated_data else "API"
                msg = (
                    f"Predicted AQI is {round(pred.predicted_aqi)} for the +{pred.horizon_hours}h "
                    f"forecast horizon, exceeding the configured threshold of {int(rule.threshold)}."
                )
                alt, _ = _get_or_create_alert(
                    db=db,
                    location_id=location_id,
                    rule_id=rule.id,
                    alert_type=AlertType.PREDICTED_THRESHOLD,
                    severity=rule.severity,
                    title=f"Forecast Alert: {rule.name}",
                    message=msg,
                    observed_value=pred.predicted_aqi,
                    threshold_value=rule.threshold,
                    detected_at=pred.created_at,
                    source_type=source_label,
                    is_prediction=True,
                    prediction_id=pred.id,
                    metadata_json={
                        "forecast_horizon": pred.horizon_hours,
                        "target_timestamp": pred.target_timestamp.isoformat(),
                        "model_name": pred.model_name,
                    },
                )
                triggered_alerts.append(alt)

        # E. CATEGORY_CHANGE Rule
        elif rule.alert_type == AlertType.CATEGORY_CHANGE:
            if len(ts_aqi_series) >= 2 and latest_category:
                prev_category = ts_aqi_series[-2]["category"]
                if prev_category and prev_category != latest_category:
                    if latest_aqi_val is not None and latest_aqi_val >= rule.threshold:
                        msg = (
                            f"Air quality category transitioned from {prev_category} to "
                            f"{latest_category} at {location.name} (current AQI: {latest_aqi_val})."
                        )
                        alt, _ = _get_or_create_alert(
                            db=db,
                            location_id=location_id,
                            rule_id=rule.id,
                            alert_type=AlertType.CATEGORY_CHANGE,
                            severity=rule.severity,
                            title=f"Category Transition: {prev_category} -> {latest_category}",
                            message=msg,
                            observed_value=float(latest_aqi_val),
                            threshold_value=rule.threshold,
                            detected_at=latest_reading.timestamp if latest_reading else datetime.now(timezone.utc),
                            source_type=source_type_str,
                            metadata_json={"previous_category": prev_category, "new_category": latest_category},
                        )
                        triggered_alerts.append(alt)

    return triggered_alerts


def acknowledge_alert(db: Session, alert_id: int) -> Alert:
    """Transitions an alert from ACTIVE to ACKNOWLEDGED."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise ValueError(f"Alert {alert_id} not found.")

    alert.status = AlertStatus.ACKNOWLEDGED
    db.commit()
    db.refresh(alert)
    return alert


def resolve_alert(db: Session, alert_id: int) -> Alert:
    """Manually resolves an alert and marks resolved_at timestamp."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise ValueError(f"Alert {alert_id} not found.")

    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert


def get_active_alerts(db: Session, location_id: Optional[int] = None) -> List[Alert]:
    """Retrieves currently ACTIVE alerts, optionally filtered by location_id."""
    query = db.query(Alert).filter(Alert.status == AlertStatus.ACTIVE)
    if location_id is not None:
        query = query.filter(Alert.location_id == location_id)
    return query.order_by(Alert.detected_at.desc()).all()
