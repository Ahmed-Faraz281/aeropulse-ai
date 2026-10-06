from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.alert import AlertResponse
from backend.app.schemas.aqi import AQIResponse
from backend.app.schemas.recommendation import RecommendationItem


class LocationWorkflowRequest(BaseModel):
    """
    Request model for resolving the nearest monitoring station from user coordinates.
    Strictly validates coordinate boundaries and OpenAQ v3 search radius limit.
    """
    latitude: float = Field(..., ge=-90.0, le=90.0, description="WGS-84 latitude in degrees (-90.0 to 90.0)")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="WGS-84 longitude in degrees (-180.0 to 180.0)")
    radius_meters: int = Field(
        default=25000,
        ge=0,
        le=25000,
        description="Search radius in meters (OpenAQ v3 API constraint: 0 <= radius <= 25,000)"
    )
    force_refresh: bool = Field(
        default=False,
        description="Bypass the 15-minute in-memory spatial resolution cache if True"
    )


class UserLocationEcho(BaseModel):
    """
    Ephemeral echo of user coordinates returned for frontend client map rendering.
    Never persisted in the database.
    """
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None


class ResolvedStationInfo(BaseModel):
    """
    Metadata for the resolved primary or alternative monitoring station.
    """
    location_id: int
    external_id: int
    external_provider: str = "OPENAQ"
    name: str
    city: str
    latitude: float
    longitude: float
    distance_km: float
    is_monitor: bool
    data_freshness: str  # "FRESH", "STALE", "UNAVAILABLE"
    last_observation_time: Optional[datetime] = None
    pollutants_monitored: List[str] = Field(default_factory=list)


class DistantStationInfo(BaseModel):
    """
    Informational metadata for a station located outside the 25km radius.
    Never substituted as the primary resolved station.
    """
    external_id: int
    name: str
    city: str
    latitude: float
    longitude: float
    distance_km: float
    notice: str = (
        "Nearest available station is located outside the configured search radius "
        "and does not represent immediate local air quality."
    )


class PredictionSummaryItem(BaseModel):
    """
    Standardized forecast item for an individual horizon.
    Strictly adheres to authoritative ML regressor outputs with no invented confidence scores.
    """
    horizon_hours: int
    predicted_aqi: Optional[float] = None
    category: Optional[str] = None
    target_timestamp: Optional[datetime] = None
    base_timestamp: Optional[datetime] = None
    model_version: Optional[str] = None
    status: str  # "PREDICTED", "INSUFFICIENT_HISTORY", "MODEL_UNAVAILABLE"
    message: Optional[str] = None


class WorkflowExecutionMetadata(BaseModel):
    """
    Diagnostic and operational metrics for the workflow execution run.
    """
    duration_seconds: float
    cache_hit: bool
    new_station_discovered: bool
    observations_ingested: int
    predictions_generated: int
    warnings: List[str] = Field(default_factory=list)


class LocationWorkflowResponse(BaseModel):
    """
    Unified response payload containing resolved station, current AQI,
    forecast predictions, active alerts, recommendations, and execution metadata.
    """
    status: str  # "SUCCESS", "PARTIAL_SUCCESS", "NO_STATIONS_FOUND", "ERROR"
    message: str
    user_location: UserLocationEcho
    resolved_station: Optional[ResolvedStationInfo] = None
    nearest_distant_station: Optional[DistantStationInfo] = None
    current_aqi: Optional[AQIResponse] = None
    predictions: List[PredictionSummaryItem] = Field(default_factory=list)
    active_alerts: List[AlertResponse] = Field(default_factory=list)
    recommendations: List[RecommendationItem] = Field(default_factory=list)
    alternative_stations: List[ResolvedStationInfo] = Field(default_factory=list)
    metadata: WorkflowExecutionMetadata
