from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class LocationBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    city: str = Field(..., min_length=2, max_length=64)
    state: str = Field(..., min_length=2, max_length=64)
    country: str = Field(default="India", max_length=64)
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude between -90 and 90")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude between -180 and 180")
    description: Optional[str] = None
    is_active: bool = True
    external_provider: Optional[str] = None
    external_id: Optional[str] = None


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=128)
    city: Optional[str] = Field(None, min_length=2, max_length=64)
    state: Optional[str] = Field(None, min_length=2, max_length=64)
    country: Optional[str] = Field(None, max_length=64)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class LocationResponse(LocationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
