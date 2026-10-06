from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.models.user import User, UserRole
from backend.app.schemas.openaq import (
    OpenAQIngestRequest,
    OpenAQIngestResponse,
    OpenAQLocationListResponse,
    OpenAQLocationNormalized,
    OpenAQSensorHoursResponse,
    OpenAQSensorListResponse,
    OpenAQSensorNormalized,
)
from backend.app.services.openaq_ingestion_service import (
    OpenAQIngestionService,
    get_openaq_ingestion_service,
)
from backend.app.services.openaq_service import (
    OpenAQAuthError,
    OpenAQConfigError,
    OpenAQNotFoundError,
    OpenAQRatelimitError,
    OpenAQService,
    OpenAQTimeoutError,
    OpenAQUpstreamError,
    OpenAQValidationError,
    get_openaq_service,
)

router = APIRouter()


def _map_openaq_exception(exc: Exception) -> None:
    """Map domain exceptions to standard HTTP status codes."""
    if isinstance(exc, OpenAQConfigError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, OpenAQAuthError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAQ authentication failed upstream: {str(exc)}",
        )
    if isinstance(exc, OpenAQNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    if isinstance(exc, OpenAQRatelimitError):
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers=headers,
        )
    if isinstance(exc, OpenAQValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if isinstance(exc, OpenAQTimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        )
    if isinstance(exc, OpenAQUpstreamError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAQ upstream service error: {str(exc)}",
        )
    if isinstance(exc, HTTPException):
        raise exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected OpenAQ connector error: {type(exc).__name__}",
    )


@router.get(
    "/locations/{location_id}",
    response_model=OpenAQLocationNormalized,
    summary="Get OpenAQ Location Details",
)
def get_openaq_location(
    location_id: int,
    service: OpenAQService = Depends(get_openaq_service),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch normalized metadata for an OpenAQ location by ID.
    Available to all authenticated roles (Admin, Analyst, Viewer).
    """
    try:
        return service.get_location(location_id=location_id)
    except Exception as exc:
        _map_openaq_exception(exc)


@router.get(
    "/locations",
    response_model=OpenAQLocationListResponse,
    summary="Search OpenAQ Locations",
)
def search_openaq_locations(
    query: Optional[str] = Query(None, description="Search term for location name"),
    country: Optional[str] = Query(None, description="2-letter ISO country code (e.g. IN)"),
    coordinates: Optional[str] = Query(None, description="Latitude,longitude coordinate pair (e.g. 13.029,77.585)"),
    radius: Optional[int] = Query(None, description="Radius in meters (0 <= radius <= 25,000)"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    page: int = Query(1, ge=1, description="Page number"),
    service: OpenAQService = Depends(get_openaq_service),
    current_user: User = Depends(get_current_user),
):
    """
    Search OpenAQ locations with optional radius filter.
    Enforces OpenAQ v3 constraint: radius must be <= 25,000 meters.
    Available to all authenticated roles (Admin, Analyst, Viewer).
    """
    try:
        results = service.search_locations(
            query=query,
            country=country,
            coordinates=coordinates,
            radius=radius,
            limit=limit,
            page=page,
        )
        return OpenAQLocationListResponse(
            total_records=len(results),
            page=page,
            limit=limit,
            locations=results,
        )
    except Exception as exc:
        _map_openaq_exception(exc)


@router.get(
    "/locations/{location_id}/sensors",
    response_model=OpenAQSensorListResponse,
    summary="Get OpenAQ Location Sensors",
)
def get_openaq_location_sensors(
    location_id: int,
    service: OpenAQService = Depends(get_openaq_service),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch all normalized sensors attached to an OpenAQ location.
    Available to all authenticated roles (Admin, Analyst, Viewer).
    """
    try:
        sensors = service.get_location_sensors(location_id=location_id)
        return OpenAQSensorListResponse(
            location_id=location_id,
            total_records=len(sensors),
            sensors=sensors,
        )
    except Exception as exc:
        _map_openaq_exception(exc)


@router.get(
    "/sensors/{sensor_id}",
    response_model=OpenAQSensorNormalized,
    summary="Get OpenAQ Sensor Details",
)
def get_openaq_sensor(
    sensor_id: int,
    service: OpenAQService = Depends(get_openaq_service),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch normalized metadata for a specific OpenAQ sensor.
    Available to all authenticated roles (Admin, Analyst, Viewer).
    """
    try:
        return service.get_sensor(sensor_id=sensor_id)
    except Exception as exc:
        _map_openaq_exception(exc)


@router.get(
    "/sensors/{sensor_id}/hours",
    response_model=OpenAQSensorHoursResponse,
    summary="Get OpenAQ Sensor Hourly Observations",
)
def get_openaq_sensor_hours(
    sensor_id: int,
    limit: int = Query(24, ge=1, le=100, description="Max hourly records to fetch"),
    datetime_from: Optional[datetime] = Query(None, description="Start time ISO timestamp"),
    datetime_to: Optional[datetime] = Query(None, description="End time ISO timestamp"),
    service: OpenAQService = Depends(get_openaq_service),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch normalized hourly measurements for an OpenAQ sensor.
    Available to all authenticated roles (Admin, Analyst, Viewer).
    """
    try:
        return service.get_sensor_hours(
            sensor_id=sensor_id,
            limit=limit,
            datetime_from=datetime_from,
            datetime_to=datetime_to,
        )
    except Exception as exc:
        _map_openaq_exception(exc)


@router.post(
    "/ingest",
    response_model=OpenAQIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest OpenAQ Observations into Database",
    dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.ANALYST))],
)
def ingest_openaq_data(
    payload: OpenAQIngestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Discovers nearby OpenAQ monitoring stations, normalizes physical units,
    and ingests real hourly observations into the AeroPulse database.
    Restricted to ADMIN and ANALYST roles (VIEWER receives HTTP 403 Forbidden).
    """
    service = OpenAQIngestionService(db=db)
    try:
        return service.ingest(payload)
    except Exception as exc:
        _map_openaq_exception(exc)

