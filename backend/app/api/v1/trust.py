import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.trust import StationTrustResponse, SystemTrustOverview
from backend.app.services.trust_service import get_station_trust, get_system_trust_overview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trust", tags=["Trust & Reliability"])


@router.get(
    "/overview",
    response_model=SystemTrustOverview,
    summary="Get System-Wide Trust, Freshness & Operational Readiness Overview",
    description="Returns aggregate freshness distribution across stations, active ML model horizons, and automation supervisor status.",
)
def get_trust_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accessible to all authenticated users (ADMIN, ANALYST, VIEWER)."""
    return get_system_trust_overview(db=db)


@router.get(
    "/station/{location_id}",
    response_model=StationTrustResponse,
    summary="Get Station Trust, Quality, Freshness & Degradation Diagnostics",
    description="Returns comprehensive data quality metrics, temporal freshness, provenance transparency, and prediction readiness for a specific monitoring station.",
)
def get_station_trust_profile(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accessible to all authenticated users (ADMIN, ANALYST, VIEWER)."""
    try:
        return get_station_trust(db=db, location_id=location_id)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ve),
        )
