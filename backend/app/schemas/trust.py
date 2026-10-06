from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DataFreshnessStatus(str, Enum):
    """Deterministic classification of station telemetry freshness."""
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class PredictionReadiness(str, Enum):
    """Operational readiness status for ML inference at a station."""
    READY = "READY"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    STALE_INPUT = "STALE_INPUT"


class StationDataFreshness(BaseModel):
    """Temporal freshness evaluation for a station's latest observation."""
    status: DataFreshnessStatus = Field(..., description="FRESH (<= 3h), STALE (3-24h), UNAVAILABLE (> 24h or missing)")
    observation_timestamp: Optional[datetime] = Field(None, description="UTC timestamp of the latest observation")
    age_hours: Optional[float] = Field(None, description="Age of the observation in decimal hours")
    age_minutes: Optional[float] = Field(None, description="Age of the observation in decimal minutes")
    message: str = Field(..., description="Human-readable explanation of freshness status")


class StationDataQuality(BaseModel):
    """Lightweight data quality and completeness summary for the observation."""
    aqi_valid: bool = Field(..., description="Whether CPCB NAQI could be calculated according to sufficiency rules")
    aqi_status: str = Field(..., description="CALCULATED, INSUFFICIENT_DATA, or INVALID_DATA")
    pollutants_available: List[str] = Field(default_factory=list, description="List of pollutants with valid measurements")
    pollutants_missing: List[str] = Field(default_factory=list, description="List of monitored pollutants with missing (None) values")
    pollutants_used_for_aqi: List[str] = Field(default_factory=list, description="Pollutants whose sub-indices contributed to NAQI")
    dominant_pollutant: Optional[str] = Field(None, description="The primary driver of the calculated AQI value")
    total_pollutants_monitored: int = Field(default=6, description="Total supported pollutants monitored")
    available_count: int = Field(..., description="Count of non-null pollutant concentrations")
    completeness_pct: float = Field(..., description="Percentage of supported pollutants present (0.0 to 100.0)")
    quality_status: str = Field(..., description="VALID, WARNING, or INVALID data triage classification")
    validation_notes: Optional[str] = Field(None, description="Detailed diagnostic notes from data validator")


class StationProvenanceTrust(BaseModel):
    """Explicit data provenance transparency metadata."""
    source_type: str = Field(..., description="API, UPLOADED, SIMULATED, PREDICTED, WHAT_IF, or DEMO")
    source_name: str = Field(..., description="Human-readable label of the upstream data source")
    provider: Optional[str] = Field(None, description="Organization or agency providing the data (e.g. OpenAQ, CPCB)")
    notice: str = Field(..., description="Transparency notice regarding physical measurement vs simulation vs estimate")


class StationPredictionTrust(BaseModel):
    """Trust and readiness assessment for future AQI prediction."""
    readiness: PredictionReadiness = Field(..., description="READY, INSUFFICIENT_HISTORY, MODEL_UNAVAILABLE, or STALE_INPUT")
    sufficient_history: bool = Field(..., description="Whether location has >= 4 continuous hourly readings")
    continuous_hourly_count: int = Field(..., description="Count of recent valid continuous hourly readings")
    model_available: bool = Field(..., description="Whether an active trained model artifact is accessible on disk")
    active_horizons: List[int] = Field(default_factory=list, description="List of horizons (+1h, +3h, etc.) ready for inference")
    reason: str = Field(..., description="Reasoning behind readiness classification")
    latest_prediction: Optional[Dict[str, Any]] = Field(None, description="Latest persisted prediction record summary, if any")


class StationDegradedState(BaseModel):
    """Graceful degradation diagnostics across domain subsystems."""
    is_degraded: bool = Field(..., description="True if any dependent subsystem is degraded or unavailable")
    openaq_accessible: bool = Field(default=True, description="Whether upstream OpenAQ API is responsive without backoff")
    ml_ready: bool = Field(default=True, description="Whether ML models and historical timeline are sufficient")
    alerts_operational: bool = Field(default=True, description="Whether alert rule evaluation is active")
    recommendations_operational: bool = Field(default=True, description="Whether preventive recommendation engine is operational")
    notes: List[str] = Field(default_factory=list, description="Actionable degradation notes")


class StationTrustResponse(BaseModel):
    """Comprehensive trust, data quality, and reliability profile for an air quality station."""
    location_id: int
    location_name: str
    city: str
    state: Optional[str] = None
    country: str
    external_provider: Optional[str] = None
    external_id: Optional[str] = None
    is_active: bool
    current_aqi: Optional[int] = None
    aqi_category: Optional[str] = None
    freshness: StationDataFreshness
    quality: StationDataQuality
    provenance: StationProvenanceTrust
    prediction: StationPredictionTrust
    automation: Dict[str, Any]
    degraded_state: StationDegradedState
    evaluated_at: datetime


class SystemTrustOverview(BaseModel):
    """System-wide trust, freshness distribution, and operational readiness summary."""
    total_locations: int
    active_locations: int
    fresh_stations_count: int
    stale_stations_count: int
    unavailable_stations_count: int
    active_model_horizons: List[int] = Field(default_factory=list)
    available_models_count: int
    automation_status: str
    automation_running: bool
    automation_paused: bool
    last_sync: Optional[datetime] = None
    next_sync: Optional[datetime] = None
    data_sources_summary: Dict[str, int] = Field(default_factory=dict)
    evaluated_at: datetime
