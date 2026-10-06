from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from backend.app.models.data_source import SourceType
from backend.app.models.air_quality import QualityStatus


class AirQualityReadingCreate(BaseModel):
    location_id: int
    timestamp: datetime

    # Pollutant concentrations (strictly optional/nullable; NEVER replaced with zero)
    pm25: Optional[float] = Field(None, description="PM2.5 concentration in µg/m³")
    pm10: Optional[float] = Field(None, description="PM10 concentration in µg/m³")
    co: Optional[float] = Field(None, description="CO concentration in mg/m³")
    no2: Optional[float] = Field(None, description="NO2 concentration in µg/m³")
    so2: Optional[float] = Field(None, description="SO2 concentration in µg/m³")
    o3: Optional[float] = Field(None, description="O3 concentration in µg/m³")

    # Environmental weather parameters
    temperature: Optional[float] = Field(None, description="Ambient temperature in °C")
    humidity: Optional[float] = Field(None, ge=0.0, le=100.0, description="Relative humidity %")

    source_id: int
    source_type: SourceType


class AirQualityReadingResponse(BaseModel):
    id: int
    location_id: int
    timestamp: datetime

    pm25: Optional[float] = None
    pm10: Optional[float] = None
    co: Optional[float] = None
    no2: Optional[float] = None
    so2: Optional[float] = None
    o3: Optional[float] = None

    temperature: Optional[float] = None
    humidity: Optional[float] = None

    source_id: int
    source_type: SourceType
    quality_status: QualityStatus
    validation_notes: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CurrentReadingResponse(BaseModel):
    location_id: int
    location_name: str
    city: str
    reading: Optional[AirQualityReadingResponse] = None
    message: Optional[str] = None
