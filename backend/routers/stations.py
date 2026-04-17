# routers/stations.py
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime
import uuid

from models import ChargingStation, Charger, User
from tortoise.exceptions import IntegrityError
from auth_middleware import require_admin, get_current_user_with_db
from crud import log_audit_event

# Pydantic schemas for request/response
class StationCreate(BaseModel):
    name: str
    latitude: float
    longitude: float
    address: str
    franchisee_id: Optional[int] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None

class StationUpdate(BaseModel):
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    franchisee_id: Optional[int] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None

class StationResponse(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    address: str
    franchisee_id: Optional[int] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class StationListResponse(BaseModel):
    data: List[StationResponse]
    total: int
    page: int
    limit: int

class ChargerBasicInfo(BaseModel):
    id: int
    charge_point_string_id: str
    name: str
    latest_status: str
    
    class Config:
        from_attributes = True

class StationDetailResponse(BaseModel):
    station: StationResponse
    chargers: List[ChargerBasicInfo]

# Create router
router = APIRouter(
    prefix="/api/admin/stations",
    tags=["Station Management"]
)

@router.get("", response_model=StationListResponse)
async def list_stations(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    sort: Optional[str] = Query("created_at", regex="^(created_at|updated_at|name)$")
):
    """List all charging stations with pagination and search"""
    
    # Build query
    query = ChargingStation.all()
    
    # Apply search filter
    if search:
        query = query.filter(name__icontains=search)
    
    # Get total count
    total = await query.count()
    
    # Apply sorting
    if sort.startswith("-"):
        query = query.order_by(f"-{sort[1:]}")
    else:
        query = query.order_by(sort)
    
    # Apply pagination
    offset = (page - 1) * limit
    stations = await query.offset(offset).limit(limit)
    
    # Convert to response models
    station_responses = [StationResponse.model_validate(station, from_attributes=True) for station in stations]
    
    return StationListResponse(
        data=station_responses,
        total=total,
        page=page,
        limit=limit
    )

@router.post("", response_model=dict, status_code=201)
async def create_station(station_data: StationCreate, admin_user: User = Depends(require_admin())):
    """Create a new charging station"""
    
    try:
        create_kwargs = {
            "name": station_data.name,
            "latitude": station_data.latitude,
            "longitude": station_data.longitude,
            "address": station_data.address,
        }
        if station_data.franchisee_id is not None:
            create_kwargs["franchisee_id"] = station_data.franchisee_id
        if station_data.state is not None:
            create_kwargs["state"] = station_data.state
        if station_data.state_code is not None:
            create_kwargs["state_code"] = station_data.state_code
        if station_data.pincode is not None:
            create_kwargs["pincode"] = station_data.pincode
        station = await ChargingStation.create(**create_kwargs)
        
        await log_audit_event(
            action="station.created",
            entity_type="station",
            entity_id=station.id,
            actor_type="admin",
            actor=admin_user,
            changes={"name": station_data.name},
        )

        return {
            "station": StationResponse.model_validate(station, from_attributes=True),
            "message": "Station created successfully"
        }
    except IntegrityError as e:
        raise HTTPException(status_code=400, detail="Station creation failed")

@router.get("/{station_id}", response_model=StationDetailResponse)
async def get_station_details(station_id: int):
    """Get station details including associated chargers"""
    
    station = await ChargingStation.filter(id=station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Get associated chargers
    chargers = await Charger.filter(station_id=station_id).all()
    
    charger_responses = [ChargerBasicInfo.model_validate(charger, from_attributes=True) for charger in chargers]
    
    return StationDetailResponse(
        station=StationResponse.model_validate(station, from_attributes=True),
        chargers=charger_responses
    )

@router.put("/{station_id}", response_model=dict)
async def update_station(station_id: int, update_data: StationUpdate, admin_user: User = Depends(require_admin())):
    """Update station information"""
    
    station = await ChargingStation.filter(id=station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Update only provided fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(station, field, value)
    
    await station.save()

    await log_audit_event(
        action="station.updated",
        entity_type="station",
        entity_id=station_id,
        actor_type="admin",
        actor=admin_user,
        changes=update_dict,
    )

    return {
        "station": StationResponse.model_validate(station, from_attributes=True),
        "message": "Station updated successfully"
    }

@router.delete("/{station_id}", response_model=dict)
async def delete_station(station_id: int, admin_user: User = Depends(require_admin())):
    """Delete a charging station (cascades to chargers)"""
    
    station = await ChargingStation.filter(id=station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Check if there are any active charging sessions
    # For now, we'll just delete - we can add transaction checks later
    
    station_name = station.name

    await station.delete()

    await log_audit_event(
        action="station.deleted",
        entity_type="station",
        entity_id=station_id,
        actor_type="admin",
        actor=admin_user,
        changes={"name": station_name},
    )

    return {"message": "Station deleted successfully"}
