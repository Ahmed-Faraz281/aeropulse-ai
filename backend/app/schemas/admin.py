from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.system_setting import SettingCategory
from backend.app.models.user import UserRole
from backend.app.schemas.user import UserResponse


# ==============================================================================
# User Administration Schemas
# ==============================================================================

class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.VIEWER
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    email: Optional[str] = Field(None, pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ==============================================================================
# Audit Log Schemas
# ==============================================================================

class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    user_id: Optional[int] = None
    username_snapshot: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    description: str
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool
    metadata_json: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ==============================================================================
# System Setting Schemas
# ==============================================================================

class SystemSettingResponse(BaseModel):
    id: int
    key: str
    value: str
    value_type: str
    description: Optional[str] = None
    category: SettingCategory
    is_sensitive: bool
    updated_by: Optional[str] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemSettingUpdate(BaseModel):
    value: str = Field(..., min_length=1, max_length=4096)


# ==============================================================================
# Admin Overview Schemas
# ==============================================================================

class UserStats(BaseModel):
    total: int
    active: int
    inactive: int
    by_role: Dict[str, int]


class LocationStats(BaseModel):
    total: int
    active: int
    inactive: int


class DataSourceStats(BaseModel):
    total: int
    active: int
    by_type: Dict[str, int]


class AlertRuleStats(BaseModel):
    total: int
    enabled: int
    disabled: int


class SystemStatusInfo(BaseModel):
    app_name: str
    version: str
    environment: str
    database_connected: bool
    database_dialect: str


class AdminOverviewResponse(BaseModel):
    users: UserStats
    locations: LocationStats
    data_sources: DataSourceStats
    alert_rules: AlertRuleStats
    system_status: SystemStatusInfo
    recent_audit_logs: List[AuditLogResponse]
