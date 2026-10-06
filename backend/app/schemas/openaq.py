from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class OpenAQSensorSummary(BaseModel):
    """Compact summary of a sensor attached to a location."""
    id: int
    name: Optional[str] = None
    parameter_id: Optional[int] = None
    parameter_name: str
    parameter_display_name: Optional[str] = None
    units: str


class OpenAQLocationNormalized(BaseModel):
    """Normalized OpenAQ location structure."""
    id: int
    name: str
    locality: Optional[str] = None
    timezone: Optional[str] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    owner_name: Optional[str] = None
    provider_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_mobile: bool = False
    is_monitor: bool = True
    instruments: List[str] = Field(default_factory=list)
    sensors: List[OpenAQSensorSummary] = Field(default_factory=list)
    datetime_first: Optional[datetime] = None
    datetime_last: Optional[datetime] = None


class OpenAQCoverageNormalized(BaseModel):
    """Temporal coverage metrics for an OpenAQ sensor."""
    expected_count: Optional[int] = None
    observed_count: Optional[int] = None
    percent_complete: Optional[float] = None
    percent_coverage: Optional[float] = None
    observed_interval: Optional[str] = None


class OpenAQSensorNormalized(BaseModel):
    """
    Normalized OpenAQ sensor structure.
    Note: OpenAQ sensors represent pollutants (e.g. pm25, no2) as well as
    environmental/meteorological parameters (e.g. temperature, relativehumidity).
    parameter_name is kept generic to support both.
    """
    id: int
    name: Optional[str] = None
    parameter_id: Optional[int] = None
    parameter_name: str
    parameter_display_name: Optional[str] = None
    units: str
    location_id: Optional[int] = None
    is_active: Optional[bool] = None  # Derived from temporal metadata or None
    datetime_first: Optional[datetime] = None
    datetime_last: Optional[datetime] = None
    coverage: Optional[OpenAQCoverageNormalized] = None
    summary_min: Optional[float] = None
    summary_max: Optional[float] = None
    summary_avg: Optional[float] = None


class OpenAQHourlyMeasurement(BaseModel):
    """Individual normalized hourly observation from OpenAQ v3 /sensors/{id}/hours."""
    datetime_from_utc: datetime
    datetime_to_utc: datetime
    datetime_from_local: Optional[str] = None
    datetime_to_local: Optional[str] = None
    value: float
    coverage_percent: Optional[float] = None
    coverage_count: Optional[int] = None


class OpenAQSensorHoursResponse(BaseModel):
    """Collection of normalized hourly measurements for a sensor."""
    sensor_id: int
    parameter_name: str
    units: str
    period: str = "hours"
    total_records: int
    measurements: List[OpenAQHourlyMeasurement] = Field(default_factory=list)


class OpenAQLocationListResponse(BaseModel):
    """Paginated list of normalized locations."""
    total_records: int
    page: int
    limit: int
    locations: List[OpenAQLocationNormalized] = Field(default_factory=list)


class OpenAQSensorListResponse(BaseModel):
    """List of normalized sensors for a given location."""
    location_id: int
    total_records: int
    sensors: List[OpenAQSensorNormalized] = Field(default_factory=list)


class OpenAQLocationSearchQuery(BaseModel):
    """Query parameters for searching OpenAQ locations with strict validation."""
    query: Optional[str] = None
    country: Optional[str] = None
    coordinates: Optional[str] = None  # "latitude,longitude"
    radius: Optional[int] = None       # in meters: 0 <= radius <= 25000
    limit: int = Field(default=20, ge=1, le=100)
    page: int = Field(default=1, ge=1)

    @field_validator("radius")
    @classmethod
    def validate_radius(cls, v: Optional[int]) -> Optional[int]:
        if v is not None:
            if v < 0 or v > 25000:
                raise ValueError("Radius must be between 0 and 25,000 meters")
        return v

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            parts = [p.strip() for p in v.split(",")]
            if len(parts) != 2:
                raise ValueError("Coordinates must be in 'latitude,longitude' format")
            try:
                lat = float(parts[0])
                lon = float(parts[1])
            except ValueError:
                raise ValueError("Coordinates must contain valid float numbers")
            if not (-90.0 <= lat <= 90.0):
                raise ValueError("Latitude must be between -90 and 90 degrees")
            if not (-180.0 <= lon <= 180.0):
                raise ValueError("Longitude must be between -180 and 180 degrees")
        return v


class OpenAQIngestRequest(BaseModel):
    """
    Request payload for OpenAQ historical ingestion and dynamic station discovery.
    Bound by safety limits: max 5 stations per request, max 14 days history.
    """
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0, description="Center latitude (-90 to 90)")
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0, description="Center longitude (-180 to 180)")
    radius: int = Field(default=25000, ge=0, le=25000, description="Discovery radius in meters (0 to 25,000m)")
    history_days: int = Field(default=7, ge=1, le=14, description="Historical days to ingest (1 to 14)")
    max_locations: int = Field(default=5, ge=1, le=5, description="Max OpenAQ stations to process (1 to 5 per request)")
    location_ids: Optional[List[int]] = Field(None, description="Optional explicit OpenAQ location IDs (max 5)")

    @field_validator("location_ids")
    @classmethod
    def validate_location_ids(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            if len(v) == 0:
                return None
            if len(v) > 5:
                raise ValueError("Maximum 5 locations allowed per ingestion request")
            for loc_id in v:
                if loc_id <= 0:
                    raise ValueError(f"Invalid location ID: {loc_id}. Must be positive integer.")
        return v

    @model_validator(mode="after")
    def validate_discovery_params(self) -> "OpenAQIngestRequest":
        if not self.location_ids:
            if self.latitude is None or self.longitude is None:
                raise ValueError("Either 'location_ids' or both 'latitude' and 'longitude' must be provided.")
        return self


class OpenAQStationIngestSummary(BaseModel):
    """Ingestion statistics for an individual OpenAQ station."""
    location_id: int
    location_name: str
    external_id: str
    sensors_selected: int
    observations_fetched: int
    observations_inserted: int
    duplicates_skipped: int
    warnings: int
    pollutants: List[str] = Field(default_factory=list)


class OpenAQIngestResponse(BaseModel):
    """Aggregated ingestion execution summary returned to client."""
    status: str  # "success", "partial_success", "no_data"
    locations_discovered: int
    locations_processed: int
    sensors_discovered: int
    sensors_selected: int
    observations_fetched: int
    observations_inserted: int
    duplicates_skipped: int
    observations_rejected: int
    validation_warnings: int
    pollutants_mapped: List[str] = Field(default_factory=list)
    earliest_observation: Optional[datetime] = None
    latest_observation: Optional[datetime] = None
    stations: List[OpenAQStationIngestSummary] = Field(default_factory=list)
    predictions_generated: int = 0
    models_retrained: bool = False
    duration_seconds: float
    errors: List[str] = Field(default_factory=list)

