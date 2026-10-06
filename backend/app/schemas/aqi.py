from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class AQIResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    location_id: int
    reading_id: int
    timestamp: datetime
    aqi: Optional[int] = None
    category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    calculation_method: str = "CPCB_INDIA_V1"
    status: str = "CALCULATED"
    pollutant_subindices: Optional[Dict[str, Optional[int]]] = None
    warnings: Optional[List[str]] = None
    message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
