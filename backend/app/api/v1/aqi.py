from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.api.deps import get_current_user
from backend.app.models.user import User
from backend.app.models.location import Location
from backend.app.models.air_quality import AirQualityReading
from backend.app.models.aqi import AQIRecord
from backend.app.schemas.aqi import AQIResponse
from backend.app.services.aqi_engine import calculate_aqi

router = APIRouter()

METHOD_VERSION = "CPCB_INDIA_V1"


def _get_or_create_aqi_record(reading: AirQualityReading, db: Session) -> AQIRecord:
    """
    Retrieves cached AQIRecord for the given reading, or executes
    calculation and persists a new record.
    """
    record = (
        db.query(AQIRecord)
        .filter(
            AQIRecord.reading_id == reading.id,
            AQIRecord.calculation_method == METHOD_VERSION,
        )
        .first()
    )
    if record:
        return record

    # Calculate using CPCB NAQI engine
    calc = calculate_aqi(
        pm25=reading.pm25,
        pm10=reading.pm10,
        no2=reading.no2,
        so2=reading.so2,
        co=reading.co,
        o3=reading.o3,
        timestamp=reading.timestamp,
    )

    record = AQIRecord(
        location_id=reading.location_id,
        reading_id=reading.id,
        timestamp=reading.timestamp,
        aqi=calc.aqi,
        category=calc.category,
        dominant_pollutant=calc.dominant_pollutant,
        calculation_method=calc.calculation_method,
        status=calc.status.value,
        pollutant_subindices=calc.pollutant_subindices,
        warnings=calc.warnings,
        message=calc.message,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get(
    "/{location_id}",
    response_model=AQIResponse,
    summary="Get Latest AQI for Location",
    description="Computes or returns the cached CPCB NAQI for the most recent reading at a location.",
)
def get_latest_aqi(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify Location exists
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {location_id} not found.",
        )

    # Fetch latest reading
    latest_reading = (
        db.query(AirQualityReading)
        .filter(AirQualityReading.location_id == location_id)
        .order_by(AirQualityReading.timestamp.desc())
        .first()
    )
    if not latest_reading:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry readings found for location ID {location_id}.",
        )

    return _get_or_create_aqi_record(latest_reading, db)


@router.get(
    "/{location_id}/history",
    response_model=List[AQIResponse],
    summary="Query Historical AQI Time-Series",
    description="Returns calculated/cached historical AQI records with optional time window and limit.",
)
def get_aqi_history(
    location_id: int,
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return (capped at 500)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify Location exists
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {location_id} not found.",
        )

    query = db.query(AirQualityReading).filter(AirQualityReading.location_id == location_id)
    if start_time is not None:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time is not None:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings = query.order_by(AirQualityReading.timestamp.desc()).limit(limit).all()

    results = []
    for reading in readings:
        results.append(_get_or_create_aqi_record(reading, db))

    return results
