from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_db, require_role
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.user import User, UserRole
from backend.app.schemas.data_source import (
    DataSourceCreate,
    DataSourceResponse,
    DataSourceUpdate,
)
from backend.app.services.audit_service import log_audit_event

router = APIRouter()


@router.get("", response_model=List[DataSourceResponse], summary="List Data Sources")
def list_data_sources(
    source_type: Optional[SourceType] = Query(None, description="Filter by source type (API, UPLOADED, SIMULATED, DEMO)"),
    is_active: Optional[bool] = Query(True, description="Filter active/inactive sources"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieves all registered air quality data source streams.
    Available to all authenticated roles.
    """
    query = db.query(DataSource)
    if source_type:
        query = query.filter(DataSource.source_type == source_type)
    if is_active is not None:
        query = query.filter(DataSource.is_active == is_active)

    return query.order_by(DataSource.name.asc()).all()


@router.post(
    "",
    response_model=DataSourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register New Data Source",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def create_data_source(
    payload: DataSourceCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Registers a new data source or provider. Restricted strictly to ADMIN role.
    """
    existing = (
        db.query(DataSource)
        .filter(DataSource.name == payload.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Data source '{payload.name}' is already registered",
        )

    data_source = DataSource(**payload.model_dump())
    db.add(data_source)
    db.flush()

    log_audit_event(
        db=db,
        actor=current_user,
        action="DATA_SOURCE_CREATED",
        resource_type="DATA_SOURCE",
        resource_id=str(data_source.id),
        description=f"Registered data source '{data_source.name}' (type: {data_source.source_type.value})",
        old_value=None,
        new_value={
            "id": data_source.id,
            "name": data_source.name,
            "source_type": data_source.source_type.value,
            "provider": data_source.provider,
            "is_active": data_source.is_active,
        },
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(data_source)
    return data_source


@router.get("/{source_id}", response_model=DataSourceResponse, summary="Get Data Source Details")
def get_data_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetches data source details by ID.
    """
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data source with ID {source_id} not found",
        )
    return source


@router.put(
    "/{source_id}",
    response_model=DataSourceResponse,
    summary="Update Data Source Attributes (Admin only)",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
def update_data_source(
    source_id: int,
    payload: DataSourceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Updates data source name, provider, description, or active status.
    Source type (provenance) is strictly immutable and cannot be altered.
    """
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data source with ID {source_id} not found",
        )

    old_snapshot = {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type.value,
        "provider": source.provider,
        "description": source.description,
        "is_active": source.is_active,
    }

    update_data = payload.model_dump(exclude_unset=True)
    # Enforce strict provenance preservation: ensure source_type cannot be mutated
    if "source_type" in update_data:
        del update_data["source_type"]

    action = "DATA_SOURCE_UPDATED"
    if "is_active" in update_data and update_data["is_active"] != source.is_active:
        action = "DATA_SOURCE_ACTIVATED" if update_data["is_active"] else "DATA_SOURCE_DEACTIVATED"

    for field, value in update_data.items():
        setattr(source, field, value)

    new_snapshot = {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type.value,
        "provider": source.provider,
        "description": source.description,
        "is_active": source.is_active,
    }

    log_audit_event(
        db=db,
        actor=current_user,
        action=action,
        resource_type="DATA_SOURCE",
        resource_id=str(source.id),
        description=f"Updated data source '{source.name}' (action: {action})",
        old_value=old_snapshot,
        new_value=new_snapshot,
        request=request,
        success=True,
    )

    db.commit()
    db.refresh(source)
    return source
