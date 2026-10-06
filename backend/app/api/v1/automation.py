import asyncio
from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.models.user import User, UserRole
from backend.app.schemas.automation import (
    AutomationActionResponse,
    AutomationStatusResponse,
    AutomationTriggerResponse,
)
from backend.app.services.audit_service import log_audit_event
from backend.app.services.automation_service import get_automation_supervisor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation", tags=["Automation"])


@router.get(
    "/status",
    response_model=AutomationStatusResponse,
    summary="Get Automation & Continuous Monitoring Status",
    description="Returns current status of the background automation supervisor, last run metrics, and next scheduled execution.",
)
def get_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accessible to all authenticated users (ADMIN, ANALYST, VIEWER)."""
    supervisor = get_automation_supervisor()
    return supervisor.get_status(db=db)


@router.post(
    "/trigger",
    response_model=AutomationTriggerResponse,
    summary="Trigger Immediate Automation Sync Cycle",
    description="Initiates an asynchronous background synchronization cycle. Rejects with 409 Conflict if a cycle is already running.",
)
async def trigger_cycle(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """ADMIN only: Starts an immediate background synchronization cycle."""
    supervisor = get_automation_supervisor()

    if supervisor._lock.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Automation job is already in progress.",
        )

    # Record administrative action in immutable audit log
    log_audit_event(
        db=db,
        actor=current_user,
        action="TRIGGER_AUTOMATION_SYNC",
        resource_type="AUTOMATION",
        resource_id="supervisor",
        description=f"Admin {current_user.username} triggered manual continuous monitoring cycle",
        request=request,
    )
    db.commit()

    # Launch cycle asynchronously in background without blocking the HTTP response
    asyncio.create_task(
        supervisor.run_sync_cycle(source=f"manual:{current_user.username}")
    )

    return AutomationTriggerResponse(
        status="accepted",
        message="Automation sync cycle initiated.",
        started_at=datetime.now(timezone.utc),
    )


@router.post(
    "/pause",
    response_model=AutomationActionResponse,
    summary="Pause Background Automation Scheduler",
    description="Temporarily halts scheduled background cycles.",
)
def pause_scheduler(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """ADMIN only: Pauses scheduled automation cycles."""
    supervisor = get_automation_supervisor()
    supervisor.pause()

    log_audit_event(
        db=db,
        actor=current_user,
        action="PAUSE_AUTOMATION_SCHEDULER",
        resource_type="AUTOMATION",
        resource_id="supervisor",
        description=f"Admin {current_user.username} paused background automation scheduler",
        request=request,
    )
    db.commit()

    return AutomationActionResponse(
        status="success",
        message="Automation scheduler paused.",
        paused=True,
    )


@router.post(
    "/resume",
    response_model=AutomationActionResponse,
    summary="Resume Background Automation Scheduler",
    description="Resumes scheduled background cycles.",
)
def resume_scheduler(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """ADMIN only: Resumes scheduled automation cycles."""
    supervisor = get_automation_supervisor()
    supervisor.resume()

    log_audit_event(
        db=db,
        actor=current_user,
        action="RESUME_AUTOMATION_SCHEDULER",
        resource_type="AUTOMATION",
        resource_id="supervisor",
        description=f"Admin {current_user.username} resumed background automation scheduler",
        request=request,
    )
    db.commit()

    return AutomationActionResponse(
        status="success",
        message="Automation scheduler resumed.",
        paused=False,
    )
