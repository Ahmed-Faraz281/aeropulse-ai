from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.models.location import Location
from backend.app.models.user import User, UserRole
from backend.app.schemas.location import LocationCreate, LocationResponse, LocationUpdate
from backend.app.services.audit_service import log_audit_event

router = APIRouter()


@router.get("", response_model=List[LocationResponse], summary="List Monitoring Locations")
def list_locations(
    city: Optional[str] = Query(None, description="Filter by city name"),
    is_active: Optional[bool] = Query(True, description="Filter active/inactive stations"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieves list of registered air quality monitoring stations.
    Available to all authenticated roles (Admin, Analyst, Viewer).
    """
    query = db.query(Location)
    if city:
        query = query.filter(Location.city.ilike(f"%{city}%"))
    if is_active is not None:
        query = query.filter(Location.is_active == is_active)

    return query.order_by(Location.name.asc()).all()


@router.post(
    "",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register New Location",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def create_location(
    payload: LocationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Registers a new physical station/location. Restricted strictly to ADMIN role.
    """
    # Check for duplicate station name in the same city
    existing = (
        db.query(Location)
        .filter(Location.name == payload.name, Location.city == payload.city)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Station '{payload.name}' already registered in {payload.city}",
        )

    location = Location(**payload.model_dump())
    db.add(location)
    db.flush()

    log_audit_event(
        db=db,
        actor=current_user,
        action="LOCATION_CREATED",
        resource_type="LOCATION",
        resource_id=str(location.id),
        description=f"Registered monitoring location '{location.name}' in {location.city}",
        old_value=None,
        new_value={
            "id": location.id,
            "name": location.name,
            "city": location.city,
            "state": location.state,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "is_active": location.is_active,
        },
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(location)
    return location


@router.get("/{location_id}", response_model=LocationResponse, summary="Get Location Details")
def get_location(
    location_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetches specific monitoring location details by ID.
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {location_id} not found",
        )
    return location


@router.put(
    "/{location_id}",
    response_model=LocationResponse,
    summary="Update Location Details",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def update_location(
    location_id: int,
    payload: LocationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Updates location attributes or coordinates. Restricted strictly to ADMIN role.
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {location_id} not found",
        )

    old_snapshot = {
        "id": location.id,
        "name": location.name,
        "city": location.city,
        "state": location.state,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "description": location.description,
        "is_active": location.is_active,
    }

    update_data = payload.model_dump(exclude_unset=True)
    action = "LOCATION_UPDATED"
    if "is_active" in update_data and update_data["is_active"] != location.is_active:
        action = "LOCATION_ACTIVATED" if update_data["is_active"] else "LOCATION_DEACTIVATED"

    for field, value in update_data.items():
        setattr(location, field, value)

    new_snapshot = {
        "id": location.id,
        "name": location.name,
        "city": location.city,
        "state": location.state,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "description": location.description,
        "is_active": location.is_active,
    }

    log_audit_event(
        db=db,
        actor=current_user,
        action=action,
        resource_type="LOCATION",
        resource_id=str(location.id),
        description=f"Updated monitoring location '{location.name}' (action: {action})",
        old_value=old_snapshot,
        new_value=new_snapshot,
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(location)
    return location
