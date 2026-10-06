import json
from typing import List, Optional, Tuple
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import check_db_connection
from backend.app.core.security import get_password_hash
from backend.app.models.alert import AlertRule
from backend.app.models.audit_log import AuditLog
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.system_setting import SystemSetting
from backend.app.models.user import User, UserRole
from backend.app.schemas.admin import (
    AdminOverviewResponse,
    AdminUserCreate,
    AdminUserUpdate,
    AlertRuleStats,
    DataSourceStats,
    LocationStats,
    SystemStatusInfo,
    UserStats,
)
from backend.app.services.audit_service import log_audit_event

ALLOWED_PREDICTION_HORIZONS = {1, 3, 6, 12, 24}


def get_admin_overview(db: Session) -> AdminOverviewResponse:
    """
    Computes system-level administrative operational indicators, entity counts,
    health diagnostics, and recent audit activity.
    """
    # 1. User metrics
    users = db.query(User).all()
    user_total = len(users)
    user_active = sum(1 for u in users if u.is_active)
    user_inactive = user_total - user_active
    by_role = {
        "admin": sum(1 for u in users if u.role == UserRole.ADMIN),
        "analyst": sum(1 for u in users if u.role == UserRole.ANALYST),
        "viewer": sum(1 for u in users if u.role == UserRole.VIEWER),
    }

    # 2. Location metrics
    locations = db.query(Location).all()
    loc_total = len(locations)
    loc_active = sum(1 for l in locations if l.is_active)
    loc_inactive = loc_total - loc_active

    # 3. Data Source metrics
    sources = db.query(DataSource).all()
    ds_total = len(sources)
    ds_active = sum(1 for s in sources if s.is_active)
    by_type = {
        st.value: sum(1 for s in sources if s.source_type == st)
        for st in SourceType
    }

    # 4. Alert Rule metrics
    rules = db.query(AlertRule).all()
    rule_total = len(rules)
    rule_enabled = sum(1 for r in rules if r.enabled)
    rule_disabled = rule_total - rule_enabled

    # 5. System & Database Health
    db_health = check_db_connection()
    dialect = "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "postgresql"

    # 6. Recent Audit Logs (latest 5)
    recent_logs = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.desc())
        .limit(5)
        .all()
    )

    return AdminOverviewResponse(
        users=UserStats(
            total=user_total,
            active=user_active,
            inactive=user_inactive,
            by_role=by_role,
        ),
        locations=LocationStats(
            total=loc_total,
            active=loc_active,
            inactive=loc_inactive,
        ),
        data_sources=DataSourceStats(
            total=ds_total,
            active=ds_active,
            by_type=by_type,
        ),
        alert_rules=AlertRuleStats(
            total=rule_total,
            enabled=rule_enabled,
            disabled=rule_disabled,
        ),
        system_status=SystemStatusInfo(
            app_name=settings.PROJECT_NAME,
            version=settings.VERSION,
            environment=settings.ENVIRONMENT,
            database_connected=db_health.get("ok", False),
            database_dialect=dialect,
        ),
        recent_audit_logs=recent_logs,
    )


def list_users_paginated(
    db: Session,
    search: Optional[str] = None,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[User], int]:
    """
    Retrieves users with optional search and filters.
    """
    query = db.query(User)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter((User.username.ilike(s)) | (User.email.ilike(s)))
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    total = query.count()
    items = (
        query.order_by(User.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return items, total


def create_user_admin(
    db: Session,
    payload: AdminUserCreate,
    actor: User,
    request: Optional[Request] = None,
) -> User:
    """
    Creates a new user account with secure password hashing and audit logging.
    """
    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' is already registered",
        )

    existing_email = db.query(User).filter(User.email == payload.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{payload.email}' is already registered",
        )

    new_user = User(
        username=payload.username,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(new_user)
    db.flush()  # Allocate ID

    log_audit_event(
        db=db,
        actor=actor,
        action="USER_CREATED",
        resource_type="USER",
        resource_id=str(new_user.id),
        description=f"Created user account {new_user.username} with role {new_user.role.value}",
        old_value=None,
        new_value={
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "role": new_user.role.value,
            "is_active": new_user.is_active,
        },
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(new_user)
    return new_user


def update_user_admin(
    db: Session,
    user_id: int,
    payload: AdminUserUpdate,
    actor: User,
    request: Optional[Request] = None,
) -> User:
    """
    Updates user role, active status, or email with self-deactivation and last-admin guards.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    # 1. Self-Deactivation / Demotion Protection
    if user.id == actor.id:
        if payload.is_active is False or (payload.role is not None and payload.role != UserRole.ADMIN):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot deactivate or demote their own account. Another administrator must perform this action.",
            )

    # 2. Last-Admin Protection
    if user.role == UserRole.ADMIN:
        is_demoting = payload.role is not None and payload.role != UserRole.ADMIN
        is_deactivating = payload.is_active is False
        if is_demoting or is_deactivating:
            active_admins = (
                db.query(User)
                .filter(User.role == UserRole.ADMIN, User.is_active == True)
                .count()
            )
            if active_admins <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate or demote the last active administrator account.",
                )

    old_snapshot = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
    }

    action = "USER_UPDATED"
    if payload.role is not None and payload.role != user.role:
        action = "USER_ROLE_CHANGED"
        user.role = payload.role

    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        action = "USER_ACTIVATED" if user.is_active else "USER_DEACTIVATED"

    if payload.email is not None and payload.email != user.email:
        # Check uniqueness
        dup = db.query(User).filter(User.email == payload.email, User.id != user_id).first()
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{payload.email}' is already in use by another user",
            )
        user.email = payload.email

    new_snapshot = {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
    }

    log_audit_event(
        db=db,
        actor=actor,
        action=action,
        resource_type="USER",
        resource_id=str(user.id),
        description=f"Updated user {user.username} (action: {action})",
        old_value=old_snapshot,
        new_value=new_snapshot,
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(user)
    return user


def get_system_settings(db: Session) -> List[SystemSetting]:
    """
    Returns all non-secret system settings.
    """
    return db.query(SystemSetting).order_by(SystemSetting.category.asc(), SystemSetting.key.asc()).all()


def update_system_setting(
    db: Session,
    key: str,
    new_value: str,
    actor: User,
    request: Optional[Request] = None,
) -> SystemSetting:
    """
    Validates and updates non-secret system configuration settings.
    Constrains forecast horizons to Phase 9 supported horizons [1, 3, 6, 12, 24].
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not setting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"System setting '{key}' not found",
        )

    # Validation rules
    if key == "ui_refresh_interval_seconds":
        try:
            val = int(new_value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Value must be a valid integer",
            )
        if val < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="UI refresh interval must be at least 5 seconds",
            )

    elif key == "min_aqi_data_sufficiency_subindices":
        try:
            val = int(new_value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Value must be a valid integer",
            )
        if val < 1 or val > 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Data sufficiency subindices requirement must be between 1 and 8",
            )

    elif key == "prediction_forecast_horizons_hours":
        try:
            horizons = json.loads(new_value)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prediction horizons must be a valid JSON array of integers",
            )
        if not isinstance(horizons, list) or not all(isinstance(h, int) for h in horizons):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Prediction horizons must be a list of integers",
            )
        unsupported = set(horizons) - ALLOWED_PREDICTION_HORIZONS
        if unsupported:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported horizon(s): {sorted(list(unsupported))}. Allowed horizons are strictly limited to {sorted(list(ALLOWED_PREDICTION_HORIZONS))}",
            )

    old_snapshot = {"key": setting.key, "value": setting.value}
    setting.value = new_value
    setting.updated_by = actor.username
    new_snapshot = {"key": setting.key, "value": setting.value}

    log_audit_event(
        db=db,
        actor=actor,
        action="CONFIG_UPDATED",
        resource_type="SYSTEM_SETTING",
        resource_id=setting.key,
        description=f"Updated configuration parameter '{setting.key}' to '{new_value}'",
        old_value=old_snapshot,
        new_value=new_snapshot,
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(setting)
    return setting
