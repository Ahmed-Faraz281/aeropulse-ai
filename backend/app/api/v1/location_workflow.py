from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.location_workflow import (
    LocationWorkflowRequest,
    LocationWorkflowResponse,
)
from backend.app.services.location_workflow_service import (
    LocationWorkflowService,
    get_location_workflow_service,
)

router = APIRouter()


@router.post(
    "/resolve",
    response_model=LocationWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve Nearest Station & Execute Location Workflow",
)
def resolve_location_workflow(
    payload: LocationWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Automatic Location-Based Workflow Orchestration:
    1. Discovers nearby official OpenAQ monitoring stations within the requested radius (<= 25km).
    2. Ranks candidate stations using the authoritative Step 2 deterministic criteria.
    3. Ingests real hourly observations if needed and computes CPCB AQI.
    4. Automatically generates multi-horizon AQI forecasts (+1h, +3h, +6h, +12h, +24h)
       using the General Multi-Station Model Suite when >= 4 continuous observations exist.
    5. Evaluates active threshold alerts and proactive prevention recommendations.
    6. Returns unified response. User GPS coordinates are strictly ephemeral and never persisted.
    Accessible to all authenticated roles (Admin, Analyst, Viewer).
    """
    service = LocationWorkflowService(db=db)
    try:
        return service.resolve_location(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Location workflow resolution error: {str(exc)}",
        )
