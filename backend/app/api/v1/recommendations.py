from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.api.deps import get_current_user
from backend.app.models.user import User
from backend.app.models.location import Location
from backend.app.schemas.recommendation import LocationRecommendationsResponse
from backend.app.services.recommendation_service import evaluate_location_recommendations

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


@router.get(
    "/{location_id}",
    response_model=LocationRecommendationsResponse,
    summary="Get explainable prevention recommendations for a location",
)
def get_recommendations_for_location(
    location_id: int,
    include_forecast: bool = Query(True, description="Include Phase 9 forecast-based recommendations"),
    include_alerts: bool = Query(True, description="Include Phase 10 active alert response recommendations"),
    horizon_hours: Optional[int] = Query(None, description="Optional specific prediction horizon in hours (1, 3, 6, 12, 24)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Evaluates and returns deterministic, explainable prevention recommendations
    based on current AQI, dominant pollutant, trend, forecast, and active alerts.

    Accessible by ADMIN, ANALYST, and VIEWER roles.
    """
    loc = db.query(Location).filter(Location.id == location_id).first()
    if not loc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location #{location_id} not found.",
        )

    return evaluate_location_recommendations(
        db=db,
        location_id=location_id,
        include_forecast=include_forecast,
        include_alerts=include_alerts,
        horizon_hours=horizon_hours,
    )
