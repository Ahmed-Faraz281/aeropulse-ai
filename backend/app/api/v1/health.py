from datetime import datetime, timezone
from fastapi import APIRouter
from backend.app.core.config import settings
from backend.app.core.database import check_db_connection

router = APIRouter()


@router.get("", summary="System Health & Connectivity Check")
def health_check():
    """
    Returns system status, service metadata, and database connection integrity.
    """
    db_health = check_db_connection()
    is_healthy = db_health.get("ok", False)

    automation_info = {"status": "disabled"}
    try:
        from backend.app.services.automation_service import get_automation_supervisor
        supervisor = get_automation_supervisor()
        automation_info = {
            "status": supervisor.status,
            "last_run": supervisor._last_run.isoformat() if supervisor._last_run else None,
            "next_run": supervisor._next_run.isoformat() if supervisor._next_run else None,
        }
    except Exception:
        pass

    return {
        "status": "healthy" if is_healthy else "degraded",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_health,
        "automation": automation_info,
    }

