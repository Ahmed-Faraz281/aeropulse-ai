from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ModelMetrics(BaseModel):
    mae: float = Field(..., description="Mean Absolute Error on validation set")
    rmse: float = Field(..., description="Root Mean Squared Error on validation set")
    r2: float = Field(..., description="Coefficient of Determination (R²) on validation set")


class ModelMetadataResponse(BaseModel):
    id: Optional[int] = None
    model_id: str
    model_name: str = "RandomForestRegressor"
    horizon_hours: int
    version: str = "1.0.0"
    training_observations: int
    training_locations_count: int
    training_start: Optional[datetime] = None
    training_end: Optional[datetime] = None
    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2: Optional[float] = None
    data_sources: List[str] = Field(default_factory=list)
    has_simulated_data: bool = False
    is_active: bool = True
    created_at: Optional[datetime] = None


class PredictionTrainRequest(BaseModel):
    location_id: Optional[int] = Field(None, description="Optional station ID; if omitted, trains the global general model")
    horizon_hours: Optional[int] = Field(1, description="Forecast horizon in hours (1, 3, 6, 12, or 24); if None, trains all 5")
    min_observations: int = Field(24, ge=5, le=10000, description="Minimum observations required for training")

    @field_validator("horizon_hours")
    @classmethod
    def validate_horizon(cls, v: Optional[int]) -> Optional[int]:
        if v is not None:
            allowed = {1, 3, 6, 12, 24}
            if v not in allowed:
                raise ValueError(f"horizon_hours must be one of {sorted(allowed)}, got {v}")
        return v


class PredictionTrainResponse(BaseModel):
    status: str = Field(..., description="Training status: SUCCESS, INSUFFICIENT_DATA, or ERROR")
    message: str = Field(..., description="Details or human-readable status explanation")
    location_id: Optional[int] = None
    horizon_hours: Optional[int] = None
    training_observations: int
    training_start: Optional[datetime] = None
    training_end: Optional[datetime] = None
    metrics: Optional[ModelMetrics] = None
    models: List[ModelMetadataResponse] = Field(default_factory=list)
    data_sources: List[str] = Field(default_factory=list)
    has_simulated_data: bool = False
    provenance_notice: str = ""


class PredictionRequest(BaseModel):
    location_id: int = Field(..., description="Station / location ID to forecast")
    horizon_hours: int = Field(1, description="Forecast horizon in hours (1, 3, 6, 12, or 24)")

    @field_validator("horizon_hours")
    @classmethod
    def validate_horizon(cls, v: int) -> int:
        allowed = {1, 3, 6, 12, 24}
        if v not in allowed:
            raise ValueError(f"horizon_hours must be one of {sorted(allowed)}, got {v}")
        return v


class PredictionResponse(BaseModel):
    id: Optional[int] = None
    location_id: int
    location_name: Optional[str] = None
    base_timestamp: datetime = Field(..., description="Timestamp of the baseline observation used")
    target_timestamp: datetime = Field(..., description="Forecast target timestamp")
    horizon_hours: int
    predicted_aqi: float = Field(..., description="Predicted numerical AQI")
    predicted_category: str = Field(..., description="CPCB NAQI Category: Good, Satisfactory, Moderate, Poor, Very Poor, Severe")
    model_name: str = "RandomForestRegressor"
    training_observations: int
    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2: Optional[float] = None
    data_sources: List[str] = Field(default_factory=list)
    has_simulated_data: bool = False
    is_prediction: bool = True
    provenance_notice: str = ""
    created_at: datetime
