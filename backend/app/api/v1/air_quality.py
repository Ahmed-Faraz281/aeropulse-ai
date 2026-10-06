from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.user import User, UserRole
from backend.app.schemas.air_quality import (
    AirQualityReadingCreate,
    AirQualityReadingResponse,
    CurrentReadingResponse,
)
from backend.app.services.data_validator import validate_reading_data

router = APIRouter()


@router.get("/current", response_model=CurrentReadingResponse, summary="Get Current Air Quality Reading")
def get_current_reading(
    location_id: int = Query(..., description="Target monitoring location ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns the most recent air quality reading for a selected location.
    Note: AQI calculation will be calculated by the AQI Engine in Phase 4.
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {location_id} not found",
        )

    latest_reading = (
        db.query(AirQualityReading)
        .filter(AirQualityReading.location_id == location_id)
        .order_by(AirQualityReading.timestamp.desc())
        .first()
    )

    if not latest_reading:
        return CurrentReadingResponse(
            location_id=location.id,
            location_name=location.name,
            city=location.city,
            reading=None,
            message="No readings recorded for this station yet.",
        )

    return CurrentReadingResponse(
        location_id=location.id,
        location_name=location.name,
        city=location.city,
        reading=AirQualityReadingResponse.model_validate(latest_reading),
    )


@router.get("/history", response_model=List[AirQualityReadingResponse], summary="Query Historical Readings")
def query_historical_readings(
    location_id: Optional[int] = Query(None, description="Filter by location ID"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    source_type: Optional[SourceType] = Query(None, description="Filter by data provenance (API, UPLOADED, SIMULATED, DEMO)"),
    quality_status: Optional[QualityStatus] = Query(None, description="Filter by data quality status"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return (capped at 1000)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Queries historical air quality time-series telemetry with multi-criteria filters.
    Includes sensible safety bounds on max query limit (1000 max).
    """
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid time window: start_time ({start_time.isoformat()}) must be before or equal to end_time ({end_time.isoformat()})",
        )

    query = db.query(AirQualityReading)

    if location_id is not None:
        query = query.filter(AirQualityReading.location_id == location_id)
    if start_time is not None:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time is not None:
        query = query.filter(AirQualityReading.timestamp <= end_time)
    if source_type is not None:
        query = query.filter(AirQualityReading.source_type == source_type)
    if quality_status is not None:
        query = query.filter(AirQualityReading.quality_status == quality_status)

    return query.order_by(AirQualityReading.timestamp.desc()).limit(limit).all()


@router.post(
    "/readings",
    response_model=AirQualityReadingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Air Quality Reading",
    dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.ANALYST))],
)
def create_reading(
    payload: AirQualityReadingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Ingests an air quality reading.
    1. Validates referenced location and data source.
    2. Performs duplicate detection based on (location_id, timestamp, source_id).
    3. Runs data quality triage (VALID, WARNING, INVALID) without silent deletion.
    4. Persists measurement.
    """
    # Verify Location exists
    location = db.query(Location).filter(Location.id == payload.location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referenced location ID {payload.location_id} does not exist",
        )

    # Verify Data Source exists
    data_source = db.query(DataSource).filter(DataSource.id == payload.source_id).first()
    if not data_source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Referenced data source ID {payload.source_id} does not exist",
        )

    # Verify provenance integrity: simulated sources cannot masquerade as measured data
    if data_source.source_type == SourceType.SIMULATED and payload.source_type != SourceType.SIMULATED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Provenance integrity violation: simulated data source {payload.source_id} "
                f"cannot submit readings claiming measured source_type '{payload.source_type.value}'"
            ),
        )

    # Duplicate Detection
    duplicate = (
        db.query(AirQualityReading)
        .filter(
            AirQualityReading.location_id == payload.location_id,
            AirQualityReading.timestamp == payload.timestamp,
            AirQualityReading.source_id == payload.source_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Duplicate reading detected for station {payload.location_id} "
                f"at timestamp {payload.timestamp.isoformat()} from source {payload.source_id}"
            ),
        )

    # Run Data Quality Triage
    quality_status, notes = validate_reading_data(payload)

    reading = AirQualityReading(
        location_id=payload.location_id,
        timestamp=payload.timestamp,
        pm25=payload.pm25,
        pm10=payload.pm10,
        co=payload.co,
        no2=payload.no2,
        so2=payload.so2,
        o3=payload.o3,
        temperature=payload.temperature,
        humidity=payload.humidity,
        source_id=payload.source_id,
        source_type=payload.source_type,
        quality_status=quality_status,
        validation_notes=notes,
    )

    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


@router.get("/readings/{reading_id}", response_model=AirQualityReadingResponse, summary="Get Specific Reading")
def get_reading_by_id(
    reading_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetches an air quality reading by its unique database ID.
    """
    reading = db.query(AirQualityReading).filter(AirQualityReading.id == reading_id).first()
    if not reading:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reading with ID {reading_id} not found",
        )
    return reading
