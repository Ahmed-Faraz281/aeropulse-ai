from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AutomationCycleSummary(BaseModel):
    """Execution summary of an individual automation synchronization cycle."""
    cycle_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    status: str = "success"  # success, partial_success, error, skipped, backoff
    stations_processed: int = 0
    stations_failed: int = 0
    observations_ingested: int = 0
    predictions_generated: int = 0
    models_retrained: bool = False
    errors: List[str] = Field(default_factory=list)


class AutomationStatusResponse(BaseModel):
    """Comprehensive operational status of the background automation supervisor."""
    status: str = Field(..., description="Operational state: DISABLED, STARTING, RUNNING, IDLE, PAUSED, BACKOFF, ERROR")
    enabled: bool = Field(..., description="Whether scheduler is enabled via configuration")
    paused: bool = Field(..., description="Whether scheduler execution is currently paused by admin")
    last_run: Optional[datetime] = Field(None, description="Timestamp when the last sync cycle completed")
    next_run: Optional[datetime] = Field(None, description="Projected timestamp for the next scheduled sync")
    last_run_duration_seconds: Optional[float] = Field(None, description="Duration in seconds of the last cycle")
    observations_ingested: int = Field(default=0, description="Observations ingested during the last cycle")
    predictions_generated: int = Field(default=0, description="Predictions generated during the last cycle")
    models_retrained: bool = Field(default=False, description="Whether models were retrained during the last cycle")
    stations_processed: int = Field(default=0, description="Number of active OpenAQ stations processed")
    stations_failed: int = Field(default=0, description="Number of stations that encountered errors")
    active_stations_count: int = Field(default=0, description="Total active OpenAQ stations registered in system")
    last_error: Optional[str] = Field(None, description="Error message from last failure, if any")
    backoff_until: Optional[datetime] = Field(None, description="Active upstream 429 rate-limit backoff expiration time")
    poll_interval_minutes: int = Field(default=60, description="Configured sync interval in minutes")
    recent_cycles: List[AutomationCycleSummary] = Field(default_factory=list, description="Recent cycle history")


class AutomationTriggerResponse(BaseModel):
    """Response returned upon triggering a manual automation cycle."""
    status: str = Field(..., description="Status of trigger request: accepted, running, or conflict")
    message: str = Field(..., description="Informational message regarding trigger outcome")
    started_at: Optional[datetime] = Field(None, description="Timestamp when the cycle began execution")


class AutomationActionResponse(BaseModel):
    """Response returned upon administrative actions (pause, resume)."""
    status: str = Field(..., description="Action status (e.g., success, error)")
    message: str = Field(..., description="Action outcome description")
    paused: bool = Field(..., description="Current paused state of the supervisor")
