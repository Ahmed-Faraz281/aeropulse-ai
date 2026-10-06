from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from backend.app.models.data_source import SourceType


class DataSourceBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=128)
    source_type: SourceType
    provider: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = None
    is_active: bool = True


class DataSourceCreate(DataSourceBase):
    pass


class DataSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=128)
    provider: Optional[str] = Field(None, max_length=128)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DataSourceResponse(DataSourceBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
