from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.models.alert import AlertSeverity, AlertStatus, AlertType


class AlertRuleBase(BaseModel):
    name: str = Field(..., max_length=128, description="Rule display name")
    alert_type: AlertType = Field(..., description="Alert classification type")
    threshold: float = Field(..., ge=0.0, description="Numerical cutoff threshold")
    duration_hours: Optional[float] = Field(None, ge=0.0, description="Duration in hours for sustained alerts")
    window_hours: Optional[float] = Field(None, ge=0.0, description="Time window in hours for rapid-rise alerts")
    severity: AlertSeverity = Field(AlertSeverity.WARNING, description="Alert severity level")
    enabled: bool = Field(True, description="Whether this rule is actively evaluated")
    applies_to_prediction: bool = Field(False, description="Whether this rule applies to forecast predictions")
    prediction_horizon_hours: Optional[int] = Field(None, description="Target forecast horizon in hours")

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("Threshold must be non-negative.")
        return v


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=128)
    alert_type: Optional[AlertType] = None
    threshold: Optional[float] = Field(None, ge=0.0)
    duration_hours: Optional[float] = Field(None, ge=0.0)
    window_hours: Optional[float] = Field(None, ge=0.0)
    severity: Optional[AlertSeverity] = None
    enabled: Optional[bool] = None
    applies_to_prediction: Optional[bool] = None
    prediction_horizon_hours: Optional[int] = None


class AlertRuleResponse(AlertRuleBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertResponse(BaseModel):
    id: int
    location_id: int
    location_name: Optional[str] = None
    rule_id: Optional[int] = None
    alert_type: AlertType
    severity: AlertSeverity
    status: AlertStatus
    title: str
    message: str
    observed_value: Optional[float] = None
    threshold_value: float
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    source_type: str = "API"
    is_prediction: bool = False
    prediction_id: Optional[int] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertEvaluationResponse(BaseModel):
    location_id: int
    location_name: Optional[str] = None
    evaluated_at: datetime
    alerts_created: int
    alerts_active: int
    alerts: List[AlertResponse]
