"""
Pydantic schemas for Phase 13 Automated Environmental & Air-Quality Report Generator.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.app.schemas.what_if import WhatIfSimulationRequest


class ReportType(str, Enum):
    LOCATION_SUMMARY = "LOCATION_SUMMARY"
    PERIOD_REPORT = "PERIOD_REPORT"
    COMPARISON_REPORT = "COMPARISON_REPORT"
    WHAT_IF_REPORT = "WHAT_IF_REPORT"


class ReportFormat(str, Enum):
    PDF = "PDF"
    JSON = "JSON"


class ReportGenerateRequest(BaseModel):
    report_type: ReportType = Field(
        ...,
        description="Type of report: LOCATION_SUMMARY, PERIOD_REPORT, COMPARISON_REPORT, or WHAT_IF_REPORT",
    )
    location_id: int = Field(
        ...,
        description="Primary location ID for the report",
    )
    start_time: Optional[datetime] = Field(
        None,
        description="Start timestamp in UTC (ISO-8601)",
    )
    end_time: Optional[datetime] = Field(
        None,
        description="End timestamp in UTC (ISO-8601)",
    )
    period_preset: Optional[str] = Field(
        None,
        description="Optional pre-set window: '24h', '48h', '7d', '30d'",
    )
    comparison_location_ids: Optional[List[int]] = Field(
        default=None,
        description="List of additional location IDs to compare against (for COMPARISON_REPORT)",
    )
    what_if_request: Optional[WhatIfSimulationRequest] = Field(
        default=None,
        description="What-If simulation request parameters (for WHAT_IF_REPORT)",
    )


class ReportPreviewResponse(BaseModel):
    report_title: str
    report_type: ReportType
    location_name: str
    city: str
    state: str
    country: str
    reporting_period: str
    generated_at: str
    provenance_summary: Dict[str, str]

    # Executive & AQI Status
    latest_aqi: Optional[int] = None
    latest_category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    aqi_statistics: Dict[str, Any] = Field(default_factory=dict)
    category_distribution: Dict[str, int] = Field(default_factory=dict)
    pollutant_summary: Dict[str, Any] = Field(default_factory=dict)
    trend_direction: str = "INSUFFICIENT_DATA"

    # Events & Alerts Counts
    anomalies_count: int = 0
    events_count: int = 0
    alerts_count: int = 0

    # Predictions
    forecast_available: bool = False
    forecast_summary: Optional[Dict[str, Any]] = None

    # Recommendations
    top_recommendations: List[Dict[str, Any]] = Field(default_factory=list)

    # Specific Scenarios
    comparison_data: Optional[List[Dict[str, Any]]] = None
    what_if_summary: Optional[Dict[str, Any]] = None

    # Text narratives
    executive_summary: str
    disclaimer: str
