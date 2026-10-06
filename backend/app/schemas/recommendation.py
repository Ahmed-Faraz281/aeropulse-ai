from datetime import datetime, timezone
import enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class RecommendationType(str, enum.Enum):
    OUTDOOR_ACTIVITY = "OUTDOOR_ACTIVITY"
    VENTILATION = "VENTILATION"
    INDOOR_AIR = "INDOOR_AIR"
    EXPOSURE_REDUCTION = "EXPOSURE_REDUCTION"
    MASK_GUIDANCE = "MASK_GUIDANCE"
    TRAVEL_TIMING = "TRAVEL_TIMING"
    HIGH_RISK_GROUP_CAUTION = "HIGH_RISK_GROUP_CAUTION"
    POLLUTANT_SPECIFIC = "POLLUTANT_SPECIFIC"
    FORECAST_PREVENTION = "FORECAST_PREVENTION"
    ALERT_RESPONSE = "ALERT_RESPONSE"


class RecommendationPriority(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class RecommendationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: RecommendationType
    title: str
    message: str
    action: str
    severity: str
    priority: RecommendationPriority
    reason: str
    triggered_by: str
    supporting_data: Dict[str, Any] = Field(default_factory=dict)
    source_type: str = "API"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    location_id: int
    category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    forecast_based: bool = False
    active: bool = True


class ForecastContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    horizon_hours: int
    predicted_aqi: float
    predicted_category: str
    target_timestamp: datetime
    model_name: str = "RandomForestRegressor"


class LocationRecommendationsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    location_name: str
    city: str
    assessment_timestamp: datetime
    current_aqi: Optional[int] = None
    current_category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    trend: Optional[str] = None
    source_type: str = "API"
    has_simulated_data: bool = False
    disclaimer: str = (
        "Recommendations are informational and based on available air-quality data. "
        "They are not medical advice. Follow official public-health guidance for your situation."
    )
    forecast_summary: Optional[ForecastContext] = None
    active_alerts_count: int = 0
    recommendations: List[RecommendationItem] = Field(default_factory=list)
