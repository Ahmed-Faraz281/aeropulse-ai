# Phase 14 — Admin Panel, Audit Logging & System Configuration Design Specification

## 1. Overview & Objectives
Phase 14 establishes a production-grade **Administration & System Management Layer** for AeroPulse AI (Intelligent Air Quality Monitoring, Prediction & Prevention System). It provides:
1. **User Administration**: Comprehensive management of accounts, active status toggles, and role assignments (`ADMIN`, `ANALYST`, `VIEWER`), backed by strict **Last-Admin Protection**.
2. **Audit Logging & Immutability**: Centralized, transaction-safe tracking of administrative mutations with automatic secret redaction, immutable historical records, and comprehensive query filters.
3. **System Configuration Management**: Structured, non-secret operational settings stored persistently in the database (`SystemSetting`), with validation ensuring compatibility with underlying engines (e.g., Phase 9 prediction horizons).
4. **Authoritative Domain APIs Enhancement**: Direct audit hooks integrated into authoritative resource routers (`/locations`, `/data-sources`, `/alerts/rules`) rather than creating duplicate CRUD proxies.
5. **Data Source Provenance Integrity**: Administrative mutation of data sources (`PUT /data-sources/{id}`) that strictly prohibits mutating `source_type`, preserving truthful provenance (`API`, `UPLOADED`, `SIMULATED`, `DEMO`).
6. **Unified Administrative Workspace**: A multi-tab dashboard in the React frontend (`Overview`, `Users`, `Locations`, `Data Sources`, `Alert Rules`, `System Settings`, `Audit Trail`) protected by backend and frontend RBAC guards.

---

## 2. Core Architectural Principles
* **Option A Architecture (Dedicated Namespace for Admin Resources)**:
  - Admin-specific resources reside under `/api/v1/admin/*` (`overview`, `users`, `audit-logs`, `settings`).
  - Domain resources remain at `/api/v1/locations`, `/api/v1/data-sources`, `/api/v1/alerts/rules` and are augmented with audit hooks.
  - Zero duplicate proxy endpoints or shadow CRUD paths.
* **Audit Immutability**:
  - No update or delete endpoints or service functions exist for `AuditLog`.
  - The Admin UI treats audit entries strictly as read-only historical evidence.
  - Audit logging is centralized in `audit_service.log_audit_event()`.
* **Provenance & Secret Redaction**:
  - `password`, `password_hash`, `token`, `secret`, `api_key`, `credentials`, `private_key` are scrubbed and replaced with `"[REDACTED]"`.
  - Passwords are never saved in snapshots or logs.
  - `source_type` cannot be mutated after data source registration.
* **Engine Non-Interference**:
  - Zero modifications to the mathematics of Phase 4 (CPCB NAQI), Phase 5 (Analytics), Phase 8 (Simulation), Phase 9 (ML Prediction), Phase 10 (Alerts), Phase 11 (Recommendations), Phase 12 (What-If), or Phase 13 (Reports).
  - Prediction horizons configured in system settings are strictly constrained to Phase 9's verified horizons: `[1, 3, 6, 12, 24]`.

---

## 3. Database Schema & Data Models

### 3.1 `AuditLog` Model (`backend/app/models/audit_log.py`)
```python
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    username_snapshot = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    resource_type = Column(String(64), nullable=False, index=True)
    resource_id = Column(String(64), nullable=True, index=True)
    description = Column(Text, nullable=False)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    success = Column(Boolean, default=True, nullable=False, index=True)
    metadata_json = Column(JSON, nullable=True)
```

### 3.2 `SystemSetting` Model (`backend/app/models/system_setting.py`)
```python
class SettingCategory(str, enum.Enum):
    GENERAL = "GENERAL"
    DATA_QUALITY = "DATA_QUALITY"
    PREDICTION = "PREDICTION"
    REPORTING = "REPORTING"
    UI = "UI"

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    value_type = Column(String(32), default="string", nullable=False)  # "string", "int", "float", "bool", "json"
    description = Column(Text, nullable=True)
    category = Column(Enum(SettingCategory), default=SettingCategory.GENERAL, nullable=False, index=True)
    is_sensitive = Column(Boolean, default=False, nullable=False)
    updated_by = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
```

### 3.3 Default System Settings Initialized
* `app_name`: `"AeroPulse AI"` (`GENERAL`, string)
* `timezone`: `"Asia/Kolkata"` (`GENERAL`, string)
* `default_dashboard_window`: `"24h"` (`UI`, string: "24h" | "48h" | "7d" | "30d")
* `ui_refresh_interval_seconds`: `30` (`UI`, int, bounds: 5 to 300)
* `min_aqi_data_sufficiency_subindices`: `3` (`DATA_QUALITY`, int, CPCB standard: 3)
* `prediction_forecast_horizons_hours`: `[1, 3, 6, 12, 24]` (`PREDICTION`, json, subset of `[1, 3, 6, 12, 24]`)
* `default_reporting_period`: `"24h"` (`REPORTING`, string: "24h" | "48h" | "7d" | "30d")

---

## 4. Backend Services & Business Logic

### 4.1 `audit_service.py` (`backend/app/services/audit_service.py`)
* `log_audit_event(...)`:
  - Extracts client IP safely: uses `request.client.host` by default. Only checks `X-Forwarded-For` if reverse proxy is explicitly enabled.
  - Sanitizes `old_value` and `new_value` by recursively redacting sensitive dictionary keys.
  - Adds `AuditLog` entity to database session within the active mutation transaction.
  - Purely additive: zero update or delete methods provided.
* `query_audit_logs(...)`:
  - Retrieves paginated audit logs with filtering by `user_id`, `action`, `resource_type`, `success`, `start_time`, `end_time`.
  - Orders results by `timestamp.desc()`.

### 4.2 `admin_service.py` (`backend/app/services/admin_service.py`)
* `get_admin_overview(db: Session)`:
  - Aggregates operational metrics:
    - User stats: total, active, inactive, breakdown by role (`admin`, `analyst`, `viewer`).
    - Location stats: total, active, inactive.
    - Data source stats: total, active, breakdown by `source_type`.
    - Alert rules: total, enabled, disabled.
    - System health: database connection status, dialect, environment mode.
    - Recent audit log records (latest 5).
* `list_users_paginated(db, search, role, is_active, page, page_size)`:
  - Returns paginated list of safe `UserResponse` records.
* `create_user_admin(db, payload, actor, request)`:
  - Checks for duplicate username or email.
  - Hashes password via `get_password_hash`.
  - Persists new user and logs `USER_CREATED` (password strictly excluded).
* `update_user_admin(db, user_id, payload, actor, request)`:
  - **Last-Admin Protection**:
    - If user being updated is an `ADMIN` and the payload attempts to set `is_active=False` or change `role` to non-admin:
      - Counts active admins: `db.query(User).filter(User.role == UserRole.ADMIN, User.is_active == True).count()`.
      - If active admin count is 1: raises `HTTP 400 Bad Request` ("Cannot deactivate or demote the last active administrator account.").
  - Applies updates and logs corresponding actions: `USER_ROLE_CHANGED`, `USER_ACTIVATED`, `USER_DEACTIVATED`.
* `get_system_settings(db)` & `update_system_setting(db, key, new_value, actor, request)`:
  - Validates value against `value_type` and domain constraints (e.g. prediction horizons must be a subset of `[1, 3, 6, 12, 24]`).
  - Persists setting and logs `CONFIG_UPDATED` with previous vs new snapshot.

---

## 5. API Endpoints Specification

### 5.1 Admin Router (`backend/app/api/v1/admin.py`)
Mounted under `/api/v1/admin`, dependencies `[Depends(require_role(UserRole.ADMIN))]`:

1. `GET /api/v1/admin/overview`:
   - Returns `AdminOverviewResponse`.
2. `GET /api/v1/admin/users`:
   - Query parameters: `search: Optional[str]`, `role: Optional[UserRole]`, `is_active: Optional[bool]`, `page: int = 1`, `page_size: int = 20`.
   - Returns `UserListResponse`.
3. `POST /api/v1/admin/users`:
   - Body: `AdminUserCreate(username, email, password, role, is_active)`.
   - Returns `UserResponse` (HTTP 201).
4. `PUT /api/v1/admin/users/{user_id}`:
   - Body: `AdminUserUpdate(email, role, is_active)`.
   - Returns `UserResponse`.
5. `GET /api/v1/admin/audit-logs`:
   - Query parameters: `action`, `resource_type`, `user_id`, `start_time`, `end_time`, `page: int = 1`, `page_size: int = 25`.
   - Returns `AuditLogListResponse`.
6. `GET /api/v1/admin/settings`:
   - Returns `List[SystemSettingResponse]`.
7. `PUT /api/v1/admin/settings/{key}`:
   - Body: `SystemSettingUpdate(value)`.
   - Returns `SystemSettingResponse`.

### 5.2 Authoritative Domain Endpoints Enhancement
1. `backend/app/api/v1/locations.py`:
   - `POST /locations`: Emits `LOCATION_CREATED`.
   - `PUT /locations/{id}`: Emits `LOCATION_UPDATED` (or `LOCATION_ACTIVATED` / `LOCATION_DEACTIVATED`).
2. `backend/app/api/v1/data_sources.py`:
   - `POST /data-sources`: Emits `DATA_SOURCE_CREATED`.
   - `PUT /data-sources/{id}`: New endpoint accepting `DataSourceUpdate(name, provider, description, is_active)`. Strictly disallows `source_type` mutations. Emits `DATA_SOURCE_UPDATED` (or `DATA_SOURCE_ACTIVATED` / `DATA_SOURCE_DEACTIVATED`).
3. `backend/app/api/v1/alerts.py`:
   - `POST /alerts/rules`: Emits `ALERT_RULE_CREATED`.
   - `PUT /alerts/rules/{id}`: Emits `ALERT_RULE_UPDATED` (or `ALERT_RULE_ENABLED` / `ALERT_RULE_DISABLED`).
   - `DELETE /alerts/rules/{id}`: Emits `ALERT_RULE_DELETED`.

---

## 6. Frontend Architecture (`frontend/src/components/admin/`)

### 6.1 Layout & Tabs
* `AdminPage.tsx`: Main workspace coordinator with tab bar:
  - **Overview Tab** (`AdminOverviewTab.tsx`): KPI overview cards, system health status pill, recent audit timeline feed.
  - **Users Tab** (`UserManagementTab.tsx`): Searchable user table, role pill filters, active status toggles, Create User modal, Edit Role modal, Last-Admin warning modal.
  - **Locations Tab** (`LocationManagementTab.tsx`): Station directory, coordinate bounds indicator, Add/Edit Location modal with lat/lon validation, activation toggle.
  - **Data Sources Tab** (`DataSourceManagementTab.tsx`): Source cards, truthful provenance badges (`API`, `UPLOADED`, `SIMULATED`, `DEMO`), locked `source_type` indicator, activation toggle.
  - **Alert Rules Tab** (`AlertRulesTab.tsx`): Rule table, threshold and severity badges, enable/disable switches, Edit Rule modal.
  - **System Settings Tab** (`SystemSettingsTab.tsx`): Grouped settings cards with inline validated inputs and reset options.
  - **Audit Trail Tab** (`AuditLogTab.tsx`): Read-only log table, date range & action filters, pagination, expandable row drawer for formatted JSON diffs.

### 6.2 Security & Navigation Guards
* In `Sidebar.tsx`: `Administration` item displays `badge: 'Admin'`.
* In `App.tsx`: Route guard checks `currentUser.role === 'admin'`. If a non-admin attempts access, renders an unauthorized warning container.
* Backend authorization strictly returns HTTP 403 Forbidden for all administrative operations performed by non-admins.

---

## 7. Testing & Verification Plan

Target: **35+ targeted Phase 14 tests** in `backend/tests/test_admin.py` and `backend/tests/test_audit.py`:
1. **User Administration**:
   - Admin listing, filtering, search.
   - User creation with valid/duplicate/invalid inputs.
   - Role updates and activation toggles.
   - Last-admin protection (preventing deactivation/demotion of last admin).
2. **Locations & Data Sources**:
   - Location creation and update with coordinate validations [-90, 90], [-180, 180].
   - Data source updates (name, provider, active status).
   - Provenance preservation: verification that `source_type` cannot be mutated.
3. **Alert Rules**:
   - Rule enable/disable and threshold updates.
   - Audit event emission on rule modification.
4. **System Settings**:
   - Retrieving settings and updating values.
   - Validation of prediction forecast horizons (only subsets of `[1, 3, 6, 12, 24]` allowed).
   - Boundary checks on UI refresh interval and data sufficiency.
5. **Audit Logging & Immutability**:
   - Verification that administrative mutations generate complete audit records.
   - Redaction of sensitive fields (`password`, `password_hash`, tokens).
   - Audit query filtering and pagination.
   - Immutability check: assertion that no audit modification/deletion routes exist.
6. **RBAC & Security**:
   - Unauthenticated requests return HTTP 401.
   - Non-admin requests (Analyst, Viewer) to `/api/v1/admin/*` return HTTP 403.
   - Admin requests return HTTP 200/201.
7. **Regression Safety**:
   - Full regression suite across all 14 phases (191 baseline + 35+ new tests = 226+ tests).
   - Frontend production build (`npm run build`) passing cleanly with zero TypeScript errors.
