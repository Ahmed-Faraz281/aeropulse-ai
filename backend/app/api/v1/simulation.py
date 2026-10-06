from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.models.user import User, UserRole
from backend.app.schemas.simulation import (
    SimulationRequest,
    SimulationResponse,
    SimulationRunMetadata,
)
from backend.app.services.simulation_service import (
    get_latest_simulation_run,
    run_simulation,
)

router = APIRouter()


@router.post(
    "/run",
    response_model=SimulationResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute Air Quality Simulation",
    dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.ANALYST))],
)
def execute_simulation(
    payload: SimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Executes a software-only synthetic air quality generation run.
    Restricted strictly to ADMIN and ANALYST roles.
    Generates validated observations, calculates AQI via CPCB NAQI standard,
    and pre-caches AQIRecords for immediate dashboard and spatial map visualization.
    """
    return run_simulation(payload, db)


@router.get(
    "/latest",
    response_model=Optional[SimulationRunMetadata],
    summary="Get Latest Simulation Run Metadata",
)
def get_latest_simulation(
    current_user: User = Depends(get_current_user),
):
    """
    Retrieves metadata summary of the most recently executed simulation run.
    Available to all authenticated users (Admin, Analyst, Viewer).
    """
    return get_latest_simulation_run()
