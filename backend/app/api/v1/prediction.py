from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, require_role
from backend.app.core.database import get_db
from backend.app.models.location import Location
from backend.app.models.prediction import ModelRegistryRecord, PredictionRecord
from backend.app.models.user import User, UserRole
from backend.app.schemas.prediction import (
    ModelMetadataResponse,
    PredictionRequest,
    PredictionResponse,
    PredictionTrainRequest,
    PredictionTrainResponse,
)
from backend.app.services.prediction_service import (
    generate_predictions,
    train_and_evaluate_model,
    train_general_models,
)

router = APIRouter(prefix="/prediction", tags=["ML Prediction"])


@router.get(
    "/models/active",
    response_model=List[ModelMetadataResponse],
    summary="Get active General ML models across horizons",
)
def get_active_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns metadata for active General Multi-Station ML models.
    Accessible to all authenticated users.
    """
    records = (
        db.query(ModelRegistryRecord)
        .filter(ModelRegistryRecord.is_active == True)
        .order_by(ModelRegistryRecord.horizon_hours.asc())
        .all()
    )
    return [
        ModelMetadataResponse(
            id=r.id,
            model_id=r.model_id,
            model_name=r.model_name,
            horizon_hours=r.horizon_hours,
            version=r.version,
            training_observations=r.training_observations,
            training_locations_count=r.training_locations_count,
            training_start=r.training_start,
            training_end=r.training_end,
            mae=r.mae,
            rmse=r.rmse,
            r2=r.r2,
            data_sources=r.data_sources or [],
            has_simulated_data=r.has_simulated_data,
            is_active=r.is_active,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.post(
    "/train",
    response_model=PredictionTrainResponse,
    summary="Train and evaluate ML prediction model (Admin/Analyst)",
)
def train_prediction_model(
    request: PredictionTrainRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.ANALYST)),
):
    # Global General Multi-Station Model Training
    if request.location_id is None:
        target_horizons = [request.horizon_hours] if request.horizon_hours else [1, 3, 6, 12, 24]
        general_results = train_general_models(
            db=db,
            horizons=target_horizons,
            min_observations=request.min_observations,
        )
        if not general_results:
            return PredictionTrainResponse(
                status="INSUFFICIENT_DATA",
                message=f"Insufficient multi-station observations to train models (required >= {request.min_observations}).",
                training_observations=0,
            )

        model_responses = [
            ModelMetadataResponse(
                model_id=res["model_id"],
                horizon_hours=res["horizon_hours"],
                training_observations=res["training_observations"],
                training_locations_count=res["training_locations_count"],
                mae=res["mae"],
                rmse=res["rmse"],
                r2=res["r2"],
                is_active=True,
            )
            for res in general_results
        ]
        total_obs = max(r.training_observations for r in model_responses)
        return PredictionTrainResponse(
            status="SUCCESS",
            message=f"Successfully trained and registered {len(model_responses)} General ML models.",
            training_observations=total_obs,
            models=model_responses,
        )

    # Location-Specific Training (Phase 9 backward compatibility)
    location = db.query(Location).filter(Location.id == request.location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {request.location_id} not found.",
        )

    result = train_and_evaluate_model(
        db=db,
        location_id=request.location_id,
        horizon_hours=request.horizon_hours or 1,
        min_observations=request.min_observations,
    )
    # Strip non-serializable model before responding
    result.pop("model", None)
    return result


@router.post(
    "/predict",
    response_model=PredictionResponse,
    summary="Generate future AQI forecast (Admin/Analyst)",
)
def run_prediction(
    request: PredictionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.ANALYST)),
):
    location = db.query(Location).filter(Location.id == request.location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {request.location_id} not found.",
        )

    try:
        pred = generate_predictions(
            db=db,
            location_id=request.location_id,
            horizon_hours=request.horizon_hours,
        )
        return pred
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate prediction.",
        )


@router.get(
    "/{location_id}/latest",
    response_model=List[PredictionResponse],
    summary="Get latest prediction records across horizons for a location",
)
def get_latest_predictions(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {location_id} not found.",
        )

    # Fetch latest prediction for each distinct horizon
    horizons = [1, 3, 6, 12, 24]
    latest_records = []
    for h in horizons:
        rec = (
            db.query(PredictionRecord)
            .filter(
                PredictionRecord.location_id == location_id,
                PredictionRecord.horizon_hours == h,
            )
            .order_by(PredictionRecord.created_at.desc())
            .first()
        )
        if rec:
            latest_records.append({
                "id": rec.id,
                "location_id": rec.location_id,
                "location_name": location.name,
                "base_timestamp": rec.base_timestamp,
                "target_timestamp": rec.target_timestamp,
                "horizon_hours": rec.horizon_hours,
                "predicted_aqi": rec.predicted_aqi,
                "predicted_category": rec.predicted_category,
                "model_name": rec.model_name,
                "training_observations": rec.training_observations,
                "mae": rec.mae,
                "rmse": rec.rmse,
                "r2": rec.r2,
                "data_sources": rec.data_sources or [],
                "has_simulated_data": rec.has_simulated_data,
                "provenance_notice": rec.provenance_notice or "",
                "created_at": rec.created_at,
            })

    return latest_records


@router.get(
    "/{location_id}/history",
    response_model=List[PredictionResponse],
    summary="Get recent historical predictions for a location",
)
def get_prediction_history(
    location_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location {location_id} not found.",
        )

    records = (
        db.query(PredictionRecord)
        .filter(PredictionRecord.location_id == location_id)
        .order_by(PredictionRecord.created_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": rec.id,
            "location_id": rec.location_id,
            "location_name": location.name,
            "base_timestamp": rec.base_timestamp,
            "target_timestamp": rec.target_timestamp,
            "horizon_hours": rec.horizon_hours,
            "predicted_aqi": rec.predicted_aqi,
            "predicted_category": rec.predicted_category,
            "model_name": rec.model_name,
            "training_observations": rec.training_observations,
            "mae": rec.mae,
            "rmse": rec.rmse,
            "r2": rec.r2,
            "data_sources": rec.data_sources or [],
            "has_simulated_data": rec.has_simulated_data,
            "provenance_notice": rec.provenance_notice or "",
            "created_at": rec.created_at,
        }
        for rec in records
    ]
