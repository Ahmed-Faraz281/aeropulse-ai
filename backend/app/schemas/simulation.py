from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class SimulationScenario(str, Enum):
    NORMAL = "NORMAL"
    RISING_POLLUTION = "RISING_POLLUTION"
    POLLUTION_SPIKE = "POLLUTION_SPIKE"
    PERSISTENT_ELEVATED = "PERSISTENT_ELEVATED"
    RECOVERY = "RECOVERY"


class SimulationRequest(BaseModel):
    location_ids: List[int] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Target monitoring station IDs for synthetic generation",
    )
    duration_hours: int = Field(
        24,
        ge=1,
        le=72,
        description="Simulation duration in hours (1 to 72 hours)",
    )
    interval_minutes: int = Field(
        60,
        ge=15,
        le=360,
        description="Temporal interval between consecutive readings (15 to 360 mins)",
    )
    scenario: SimulationScenario = Field(
        SimulationScenario.NORMAL,
        description="Simulation scenario dynamics profile",
    )
    intensity: float = Field(
        1.0,
        ge=0.1,
        le=3.0,
        description="Scaling factor for baseline pollutant concentrations",
    )
    seed: Optional[int] = Field(
        None,
        description="Optional integer seed for deterministic pseudo-random sequence",
    )


class SimulationResponse(BaseModel):
    status: str = Field("completed", description="Execution status")
    source_type: str = Field("SIMULATED", description="Data provenance designation")
    locations: int = Field(..., description="Number of locations processed")
    readings_generated: int = Field(..., description="Total synthetic observations produced")
    readings_inserted: int = Field(..., description="Readings successfully committed to database")
    readings_skipped: int = Field(..., description="Readings skipped due to unique timestamp conflicts")
    scenario: SimulationScenario = Field(..., description="Executed scenario dynamic")
    started_at: datetime = Field(..., description="Simulation start timestamp")
    completed_at: datetime = Field(..., description="Simulation completion timestamp")
    duration_seconds: float = Field(..., description="Processing duration in seconds")
    seed: Optional[int] = Field(None, description="Applied pseudo-random seed if specified")

    model_config = ConfigDict(from_attributes=True)


class SimulationRunMetadata(BaseModel):
    scenario: SimulationScenario
    location_count: int
    readings_generated: int
    readings_inserted: int
    readings_skipped: int
    started_at: datetime
    completed_at: datetime
    seed: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
