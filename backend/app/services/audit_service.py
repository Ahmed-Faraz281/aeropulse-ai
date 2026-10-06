from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.user import User

REDACTED_KEYS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "secret",
    "secret_key",
    "api_key",
    "credentials",
    "private_key",
}


def sanitize_audit_dict(data: Any) -> Any:
    """
    Recursively scans and sanitizes dictionary objects, replacing sensitive
    credentials, tokens, and password hashes with '[REDACTED]'.
    """
    if data is None:
        return None

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if str(k).lower() in REDACTED_KEYS:
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_audit_dict(v)
        return sanitized

    if isinstance(data, list):
        return [sanitize_audit_dict(item) for item in data]

    return data


def resolve_client_ip(request: Optional[Request]) -> Optional[str]:
    """
    Resolves client IP address safely preferring request.client.host.
    Does not blindly trust unverified X-Forwarded-For headers.
    """
    if not request or not request.client:
        return None
    return request.client.host


def log_audit_event(
    db: Session,
    actor: Any,
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    description: str,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    request: Optional[Request] = None,
    success: bool = True,
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """
    Appends an immutable AuditLog record to the active transaction.
    The caller commits the database session to ensure atomic persistence
    alongside the domain mutation.
    """
    user_id = None
    username_snapshot = "SYSTEM"

    if isinstance(actor, User):
        user_id = actor.id
        username_snapshot = actor.username
    elif isinstance(actor, str):
        username_snapshot = actor

    ip_address = resolve_client_ip(request)
    user_agent = None
    if request:
        user_agent = request.headers.get("user-agent", "")[:255]

    safe_old = sanitize_audit_dict(old_value)
    safe_new = sanitize_audit_dict(new_value)
    safe_meta = sanitize_audit_dict(metadata)

    log_entry = AuditLog(
        timestamp=datetime.now(timezone.utc),
        user_id=user_id,
        username_snapshot=username_snapshot,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        description=description,
        old_value=safe_old,
        new_value=safe_new,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        metadata_json=safe_meta,
    )
    db.add(log_entry)
    return log_entry


def query_audit_logs(
    db: Session,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[int] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 25,
) -> Tuple[List[AuditLog], int]:
    """
    Queries audit logs ordered newest-first with pagination and filters.
    """
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if start_time:
        query = query.filter(AuditLog.timestamp >= start_time)
    if end_time:
        query = query.filter(AuditLog.timestamp <= end_time)

    page = max(1, page)
    page_size = max(1, min(page_size, 100))

    total = query.count()
    items = (
        query.order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return items, total
