from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, require_role
from backend.app.core.database import get_db
from backend.app.models.alert import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from backend.app.models.location import Location
from backend.app.models.user import User, UserRole
from backend.app.schemas.alert import (
    AlertEvaluationResponse,
    AlertResponse,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
)
from backend.app.services.alert_service import (
    acknowledge_alert,
    ensure_default_alert_rules,
    evaluate_location_alerts,
    resolve_alert,
)
from backend.app.services.audit_service import log_audit_event

router = APIRouter(prefix="/alerts", tags=["Automated Alerts"])


# ==============================================================================
# Alert Rules Endpoints (Admin write, Authenticated read)
# ==============================================================================

@router.get(
    "/rules",
    response_model=List[AlertRuleResponse],
    summary="List all alert configuration rules",
)
def list_alert_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_default_alert_rules(db)
    return db.query(AlertRule).all()


@router.post(
    "/rules",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new alert rule (Admin only)",
)
def create_alert_rule(
    rule_in: AlertRuleCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    rule = AlertRule(**rule_in.model_dump())
    db.add(rule)
    db.flush()

    log_audit_event(
        db=db,
        actor=current_user,
        action="ALERT_RULE_CREATED",
        resource_type="ALERT_RULE",
        resource_id=str(rule.id),
        description=f"Created alert rule '{rule.name}' with threshold {rule.threshold}",
        old_value=None,
        new_value={
            "id": rule.id,
            "name": rule.name,
            "alert_type": rule.alert_type.value,
            "threshold": rule.threshold,
            "severity": rule.severity.value,
            "enabled": rule.enabled,
        },
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(rule)
    return rule


@router.put(
    "/rules/{rule_id}",
    response_model=AlertRuleResponse,
    summary="Update an existing alert rule (Admin only)",
)
def update_alert_rule(
    rule_id: int,
    rule_in: AlertRuleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert rule {rule_id} not found.",
        )

    old_snapshot = {
        "id": rule.id,
        "name": rule.name,
        "alert_type": rule.alert_type.value,
        "threshold": rule.threshold,
        "severity": rule.severity.value,
        "enabled": rule.enabled,
    }

    update_data = rule_in.model_dump(exclude_unset=True)
    action = "ALERT_RULE_UPDATED"
    if "enabled" in update_data and update_data["enabled"] != rule.enabled:
        action = "ALERT_RULE_ENABLED" if update_data["enabled"] else "ALERT_RULE_DISABLED"

    for field, val in update_data.items():
        setattr(rule, field, val)

    new_snapshot = {
        "id": rule.id,
        "name": rule.name,
        "alert_type": rule.alert_type.value,
        "threshold": rule.threshold,
        "severity": rule.severity.value,
        "enabled": rule.enabled,
    }

    log_audit_event(
        db=db,
        actor=current_user,
        action=action,
        resource_type="ALERT_RULE",
        resource_id=str(rule.id),
        description=f"Updated alert rule '{rule.name}' (action: {action})",
        old_value=old_snapshot,
        new_value=new_snapshot,
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(rule)
    return rule


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an alert rule (Admin only)",
)
def delete_alert_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert rule {rule_id} not found.",
        )

    old_snapshot = {
        "id": rule.id,
        "name": rule.name,
        "alert_type": rule.alert_type.value,
        "threshold": rule.threshold,
        "severity": rule.severity.value,
        "enabled": rule.enabled,
    }

    log_audit_event(
        db=db,
        actor=current_user,
        action="ALERT_RULE_DELETED",
        resource_type="ALERT_RULE",
        resource_id=str(rule.id),
        description=f"Deleted alert rule '{rule.name}'",
        old_value=old_snapshot,
        new_value=None,
        request=request,
        success=True,
    )

    db.delete(rule)
    db.commit()
    return None


# ==============================================================================
# Alert Evaluation & Operational Endpoints
# ==============================================================================

@router.post(
    "/evaluate/{location_id}",
    response_model=AlertEvaluationResponse,
    summary="Trigger alert evaluation for a monitored station (Admin/Analyst)",
)
def evaluate_alerts_for_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.ANALYST)),
):
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {location_id} not found.",
        )

    alerts = evaluate_location_alerts(db, location_id)
    active_count = (
        db.query(Alert)
        .filter(Alert.location_id == location_id, Alert.status == AlertStatus.ACTIVE)
        .count()
    )

    alert_responses = [
        AlertResponse(
            id=a.id,
            location_id=a.location_id,
            location_name=location.name,
            rule_id=a.rule_id,
            alert_type=a.alert_type,
            severity=a.severity,
            status=a.status,
            title=a.title,
            message=a.message,
            observed_value=a.observed_value,
            threshold_value=a.threshold_value,
            detected_at=a.detected_at,
            resolved_at=a.resolved_at,
            source_type=a.source_type,
            is_prediction=a.is_prediction,
            prediction_id=a.prediction_id,
            metadata_json=a.metadata_json,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]

    return AlertEvaluationResponse(
        location_id=location_id,
        location_name=location.name,
        evaluated_at=datetime.now(timezone.utc),
        alerts_created=len(alerts),
        alerts_active=active_count,
        alerts=alert_responses,
    )


@router.get(
    "",
    response_model=List[AlertResponse],
    summary="Query alerts with optional filters",
)
def list_alerts(
    location_id: Optional[int] = None,
    severity: Optional[AlertSeverity] = None,
    alert_type: Optional[AlertType] = None,
    status: Optional[AlertStatus] = None,
    source_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Alert).join(Alert.location)

    if location_id:
        query = query.filter(Alert.location_id == location_id)
    if severity:
        query = query.filter(Alert.severity == severity)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)
    if status:
        query = query.filter(Alert.status == status)
    if source_type:
        query = query.filter(Alert.source_type == source_type)

    alerts = query.order_by(Alert.detected_at.desc()).limit(limit).all()

    return [
        AlertResponse(
            id=a.id,
            location_id=a.location_id,
            location_name=a.location.name if a.location else None,
            rule_id=a.rule_id,
            alert_type=a.alert_type,
            severity=a.severity,
            status=a.status,
            title=a.title,
            message=a.message,
            observed_value=a.observed_value,
            threshold_value=a.threshold_value,
            detected_at=a.detected_at,
            resolved_at=a.resolved_at,
            source_type=a.source_type,
            is_prediction=a.is_prediction,
            prediction_id=a.prediction_id,
            metadata_json=a.metadata_json,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]


@router.get(
    "/active",
    response_model=List[AlertResponse],
    summary="Query currently active alerts",
)
def list_active_alerts(
    location_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Alert).join(Alert.location).filter(
        Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED])
    )
    if location_id:
        query = query.filter(Alert.location_id == location_id)

    alerts = query.order_by(Alert.detected_at.desc()).all()

    return [
        AlertResponse(
            id=a.id,
            location_id=a.location_id,
            location_name=a.location.name if a.location else None,
            rule_id=a.rule_id,
            alert_type=a.alert_type,
            severity=a.severity,
            status=a.status,
            title=a.title,
            message=a.message,
            observed_value=a.observed_value,
            threshold_value=a.threshold_value,
            detected_at=a.detected_at,
            resolved_at=a.resolved_at,
            source_type=a.source_type,
            is_prediction=a.is_prediction,
            prediction_id=a.prediction_id,
            metadata_json=a.metadata_json,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]


@router.get(
    "/{alert_id}",
    response_model=AlertResponse,
    summary="Get single alert by ID",
)
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found.",
        )

    return AlertResponse(
        id=alert.id,
        location_id=alert.location_id,
        location_name=alert.location.name if alert.location else None,
        rule_id=alert.rule_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        status=alert.status,
        title=alert.title,
        message=alert.message,
        observed_value=alert.observed_value,
        threshold_value=alert.threshold_value,
        detected_at=alert.detected_at,
        resolved_at=alert.resolved_at,
        source_type=alert.source_type,
        is_prediction=alert.is_prediction,
        prediction_id=alert.prediction_id,
        metadata_json=alert.metadata_json,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertResponse,
    summary="Acknowledge an active alert (Admin/Analyst)",
)
def acknowledge_alert_endpoint(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.ANALYST)),
):
    try:
        updated = acknowledge_alert(db, alert_id)
        return AlertResponse(
            id=updated.id,
            location_id=updated.location_id,
            location_name=updated.location.name if updated.location else None,
            rule_id=updated.rule_id,
            alert_type=updated.alert_type,
            severity=updated.severity,
            status=updated.status,
            title=updated.title,
            message=updated.message,
            observed_value=updated.observed_value,
            threshold_value=updated.threshold_value,
            detected_at=updated.detected_at,
            resolved_at=updated.resolved_at,
            source_type=updated.source_type,
            is_prediction=updated.is_prediction,
            prediction_id=updated.prediction_id,
            metadata_json=updated.metadata_json,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post(
    "/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Manually resolve an alert (Admin/Analyst)",
)
def resolve_alert_endpoint(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.ANALYST)),
):
    try:
        updated = resolve_alert(db, alert_id)
        return AlertResponse(
            id=updated.id,
            location_id=updated.location_id,
            location_name=updated.location.name if updated.location else None,
            rule_id=updated.rule_id,
            alert_type=updated.alert_type,
            severity=updated.severity,
            status=updated.status,
            title=updated.title,
            message=updated.message,
            observed_value=updated.observed_value,
            threshold_value=updated.threshold_value,
            detected_at=updated.detected_at,
            resolved_at=updated.resolved_at,
            source_type=updated.source_type,
            is_prediction=updated.is_prediction,
            prediction_id=updated.prediction_id,
            metadata_json=updated.metadata_json,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
