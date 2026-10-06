from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.recommendation import RecommendationItem


class WhatIfSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: int
    reading_id: Optional[int] = None
    pollutant_changes: Dict[str, float] = Field(
        ...,
        description="Percentage changes for pollutants, e.g. {'pm25': 20.0, 'no2': -15.0}",
    )


class BaselineState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    location_name: str
    city: str
    timestamp: datetime
    source_type: str
    pollutant_values: Dict[str, Optional[float]]
    pollutant_subindices: Dict[str, Optional[int]]
    aqi: Optional[int] = None
    category: Optional[str] = None
    dominant_pollutant: Optional[str] = None


class ScenarioState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    modified_pollutant_values: Dict[str, Optional[float]]
    pollutant_changes_percent: Dict[str, float]
    pollutant_subindices: Dict[str, Optional[int]]
    simulated_aqi: Optional[int] = None
    category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    provenance: str = "WHAT_IF / SIMULATED"
    is_valid: bool = True
    warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None


class ThresholdImpact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    crosses_threshold: bool
    rule_name: Optional[str] = None
    threshold_value: Optional[float] = None
    severity: Optional[str] = None
    message: Optional[str] = None


class ImpactAnalysis(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aqi_delta: Optional[int] = None
    aqi_percent_delta: Optional[float] = None
    category_before: Optional[str] = None
    category_after: Optional[str] = None
    category_transition: Optional[str] = None
    dominant_pollutant_before: Optional[str] = None
    dominant_pollutant_after: Optional[str] = None
    dominant_pollutant_transition: Optional[str] = None
    direction: str  # IMPROVED, WORSENED, UNCHANGED
    threshold_impact: Optional[ThresholdImpact] = None


class WhatIfSimulationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    baseline: BaselineState
    scenario: ScenarioState
    impact: ImpactAnalysis
    recommendations: List[RecommendationItem] = Field(default_factory=list)
    calculation_method: str = "CPCB_INDIA_V1"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    baseline_provenance: str
    scenario_provenance: str = "WHAT_IF / SIMULATED"
    disclaimer: str
