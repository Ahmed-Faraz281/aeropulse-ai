from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.api.deps import get_current_user
from backend.app.models.user import User
from backend.app.schemas.what_if import (
    WhatIfSimulationRequest,
    WhatIfSimulationResponse,
)
from backend.app.services.what_if_service import run_what_if_simulation

router = APIRouter(prefix="/what-if", tags=["What-If Simulation"])


@router.post(
    "/simulate",
    response_model=WhatIfSimulationResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute hypothetical What-If pollution simulation",
)
def simulate_what_if(
    request: WhatIfSimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Simulates hypothetical pollutant variations (+/- %) on the latest observation
    for a monitored station, recalculating AQI, CPCB category, dominant pollutant,
    impact delta, threshold crossing, and prevention recommendations.

    Read-only and non-destructive: zero rows inserted or mutated in the database.
    Accessible by ADMIN, ANALYST, and VIEWER roles.
    """
    return run_what_if_simulation(db=db, request=request)
