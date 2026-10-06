from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, require_role
from backend.app.models.user import User, UserRole
from backend.app.schemas.admin import (
    AdminOverviewResponse,
    AdminUserCreate,
    AdminUserUpdate,
    AuditLogListResponse,
    AuditLogResponse,
    SystemSettingResponse,
    SystemSettingUpdate,
    UserListResponse,
)
from backend.app.schemas.user import UserResponse
from backend.app.services.admin_service import (
    create_user_admin,
    get_admin_overview,
    get_system_settings,
    list_users_paginated,
    update_system_setting,
    update_user_admin,
)
from backend.app.services.audit_service import query_audit_logs

router = APIRouter(
    prefix="/admin",
    tags=["Administration"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


# ==============================================================================
# Overview Endpoint
# ==============================================================================

@router.get(
    "/overview",
    response_model=AdminOverviewResponse,
    summary="Get Administrative Overview & System Health",
)
def get_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Returns high-level system indicators: user counts, active locations,
    data source distributions, alert rules status, and recent audit logs.
    """
    return get_admin_overview(db)


# ==============================================================================
# User Administration Endpoints
# ==============================================================================

@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List Users with Search & Filtering",
)
def get_users(
    search: Optional[str] = Query(None, description="Search by username or email"),
    role: Optional[UserRole] = Query(None, description="Filter by user role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Retrieves paginated user directory. Passwords and hashes are strictly excluded.
    """
    items, total = list_users_paginated(
        db=db,
        search=search,
        role=role,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create New User Account",
)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Creates a new user account with secure password hashing and audit logging.
    """
    user = create_user_admin(db=db, payload=payload, actor=current_user, request=request)
    return UserResponse.model_validate(user)


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update User Role or Status",
)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Updates user role, active status, or email. Protected against self-deactivation
    and demotion of the last active administrator.
    """
    user = update_user_admin(
        db=db,
        user_id=user_id,
        payload=payload,
        actor=current_user,
        request=request,
    )
    return UserResponse.model_validate(user)


# ==============================================================================
# Audit Logs Endpoints
# ==============================================================================

@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="Query Immutable Audit Trail",
)
def get_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action name"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    user_id: Optional[int] = Query(None, description="Filter by actor user ID"),
    start_time: Optional[datetime] = Query(None, description="Filter by minimum timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter by maximum timestamp"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Retrieves paginated, read-only audit log records ordered newest first.
    Zero update or delete methods exist.
    """
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid time window: start_time ({start_time.isoformat()}) must be before or equal to end_time ({end_time.isoformat()})",
        )

    items, total = query_audit_logs(
        db=db,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ==============================================================================
# System Settings Endpoints
# ==============================================================================

@router.get(
    "/settings",
    response_model=List[SystemSettingResponse],
    summary="List Non-Secret System Settings",
)
def list_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Returns all non-secret operational system parameters.
    """
    settings_list = get_system_settings(db)
    return [SystemSettingResponse.model_validate(s) for s in settings_list]


@router.put(
    "/settings/{key}",
    response_model=SystemSettingResponse,
    summary="Update Non-Secret System Setting",
)
def update_setting(
    key: str,
    payload: SystemSettingUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Validates and updates an operational setting with audit logging.
    Forecast horizons are strictly constrained to Phase 9 supported horizons [1, 3, 6, 12, 24].
    """
    setting = update_system_setting(
        db=db,
        key=key,
        new_value=payload.value,
        actor=current_user,
        request=request,
    )
    return SystemSettingResponse.model_validate(setting)
