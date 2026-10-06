from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class MetricStatistics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    count: int
    mean: Optional[float] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    median: Optional[float] = None
    stddev: Optional[float] = None


class LocationAnalyticsSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    location_name: str
    city: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    aqi_statistics: MetricStatistics
    pollutant_statistics: Dict[str, MetricStatistics]
    trend_direction: str


class TimeAggregatedPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: str
    average: float
    maximum: float
    count: int


class AnomalyItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    location_id: Optional[int] = None
    metric: str
    observed_value: float
    expected_value: float
    score: float
    severity: str
    reason: str


class PollutionEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: Optional[int] = None
    start_time: datetime
    end_time: datetime
    duration_hours: float
    max_aqi: int
    dominant_pollutant: Optional[str] = None
    increase_percentage: float = 0.0
    detection_reason: str


class LocationComparisonItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    location_name: str
    city: str
    average_aqi: Optional[float] = None
    max_aqi: Optional[int] = None
    observation_count: int
    dominant_pollutant: Optional[str] = None


class HotspotIndicatorItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: int
    location_name: str
    city: str
    mean_aqi: Optional[float] = None
    max_aqi: Optional[int] = None
    observation_count: int
    high_pollution_hours: int
    event_count: int
