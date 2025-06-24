# routers/chargers.py
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime
import uuid
import logging

from models import Charger, ChargingStation, Connector, Transaction, OCPPLog
from tortoise.exceptions import IntegrityError

logger = logging.getLogger(__name__)

# Pydantic schemas
class ConnectorInput(BaseModel):
    connector_id: int
    connector_type: str
    max_power_kw: Optional[float] = None

class ChargerCreate(BaseModel):
    station_id: int
    name: str
    model: Optional[str] = None
    vendor: Optional[str] = None
    serial_number: Optional[str] = None
    connectors: List[ConnectorInput]

class ChargerUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None
    latest_status: Optional[str] = None

class ChargerResponse(BaseModel):
    id: int
    charge_point_string_id: str
    station_id: int
    name: str
    model: Optional[str]
    vendor: Optional[str]
    serial_number: Optional[str]
    latest_status: str
    last_heart_beat_time: Optional[datetime]
    connection_status: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ChargerListResponse(BaseModel):
    data: List[ChargerResponse]
    total: int
    page: int
    limit: int

class ConnectorResponse(BaseModel):
    id: int
    connector_id: int
    connector_type: str
    max_power_kw: Optional[float]
    
    class Config:
        from_attributes = True

class StationBasicInfo(BaseModel):
    id: int
    name: str
    address: str
    
    class Config:
        from_attributes = True

class TransactionBasicInfo(BaseModel):
    id: int
    user_id: int
    start_time: datetime
    transaction_status: str
    
    class Config:
        from_attributes = True

class ChargerDetailResponse(BaseModel):
    charger: ChargerResponse
    station: StationBasicInfo
    connectors: List[ConnectorResponse]
    current_transaction: Optional[TransactionBasicInfo] = None

class OCPPLogResponse(BaseModel):
    id: int
    direction: str
    message_type: str
    payload: Dict
    timestamp: datetime
    
    class Config:
        from_attributes = True

class LogsListResponse(BaseModel):
    data: List[OCPPLogResponse]
    total: int
    page: int
    limit: int

# Create router
router = APIRouter(
    prefix="/api/admin/chargers",
    tags=["Charger Management"]
)

# Import Redis manager for connection status
from redis_manager import redis_manager

# Import the global connected_charge_points from main.py
# This is a bit hacky but works for now - in production you'd use a proper state manager
def get_connected_charge_points():
    from main import connected_charge_points
    return connected_charge_points

async def get_bulk_connection_status(chargers: List[Charger]) -> Dict[str, bool]:
    """Get connection status for multiple chargers efficiently"""
    # Get all connected chargers from Redis at once
    connected_charger_ids = set(await redis_manager.get_all_connected_chargers())
    
    current_time = datetime.now()
    status_dict = {}
    
    for charger in chargers:
        # Check Redis connection first
        is_connected_redis = charger.charge_point_string_id in connected_charger_ids
        if not is_connected_redis:
            status_dict[charger.charge_point_string_id] = False
            continue
        
        # Check heartbeat timeout (5 minutes)
        if not charger.last_heart_beat_time:
            status_dict[charger.charge_point_string_id] = False
            continue
        
        time_diff = current_time - charger.last_heart_beat_time.replace(tzinfo=None)
        status_dict[charger.charge_point_string_id] = time_diff.total_seconds() <= 300
    
    return status_dict

def charger_to_response(charger: Charger, connection_status: bool) -> ChargerResponse:
    """Convert a Charger model to ChargerResponse with connection status"""
    return ChargerResponse(
        id=charger.id,
        charge_point_string_id=charger.charge_point_string_id,
        station_id=charger.station_id,
        name=charger.name,
        model=charger.model,
        vendor=charger.vendor,
        serial_number=charger.serial_number,
        latest_status=charger.latest_status,
        last_heart_beat_time=charger.last_heart_beat_time,
        created_at=charger.created_at,
        updated_at=charger.updated_at,
        connection_status=connection_status
    )

@router.get("", response_model=ChargerListResponse)
async def list_chargers(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    station_id: Optional[int] = None,
    search: Optional[str] = None,
    sort: Optional[str] = Query("created_at", regex="^(created_at|updated_at|name|latest_status)$")
):
    """List all chargers with filtering options"""
    
    query = Charger.all()
    
    # Apply filters
    if status:
        query = query.filter(latest_status=status)
    if station_id:
        query = query.filter(station_id=station_id)
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
    chargers = await query.offset(offset).limit(limit)
    
    # Get connection status for all chargers efficiently
    connection_status_dict = await get_bulk_connection_status(chargers)
    
    # Build response with connection status
    charger_responses = []
    for charger in chargers:
        connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
        charger_responses.append(charger_to_response(charger, connection_status))
    
    return ChargerListResponse(
        data=charger_responses,
        total=total,
        page=page,
        limit=limit
    )

@router.post("", response_model=dict, status_code=201)
async def create_charger(charger_data: ChargerCreate):
    """Onboard a new charger"""
    
    # Verify station exists
    station = await ChargingStation.filter(id=charger_data.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Generate unique charge point ID
    charge_point_id = str(uuid.uuid4())
    
    try:
        # Create charger
        charger = await Charger.create(
            charge_point_string_id=charge_point_id,
            station_id=charger_data.station_id,
            name=charger_data.name,
            model=charger_data.model,
            vendor=charger_data.vendor,
            serial_number=charger_data.serial_number,
            latest_status="UNAVAILABLE"
        )
        
        # Create connectors
        for connector_input in charger_data.connectors:
            await Connector.create(
                charger_id=charger.id,
                connector_id=connector_input.connector_id,
                connector_type=connector_input.connector_type,
                max_power_kw=connector_input.max_power_kw
            )
        
        # Generate OCPP URL
        # You should configure this based on your actual domain
        ocpp_url = f"ws://your-domain.com/ocpp/{charge_point_id}"
        
        # Get connection status for response (new charger won't be connected yet)
        connection_status_dict = await get_bulk_connection_status([charger])
        connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
        return {
            "charger": charger_to_response(charger, connection_status),
            "ocpp_url": ocpp_url,
            "message": "Charger onboarded successfully"
        }
    except IntegrityError as e:
        raise HTTPException(status_code=400, detail="Charger creation failed - check serial number uniqueness")

@router.get("/{charger_id}", response_model=ChargerDetailResponse)
async def get_charger_details(charger_id: int):
    """Get detailed charger information"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Get related data
    station = await ChargingStation.filter(id=charger.station_id).first()
    connectors = await Connector.filter(charger_id=charger_id).all()
    
    # Get current active transaction if any
    current_transaction = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
    ).first()
    
    # Get connection status
    connection_status_dict = await get_bulk_connection_status([charger])
    connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
    # Build response
    response = ChargerDetailResponse(
        charger=charger_to_response(charger, connection_status),
        station=StationBasicInfo.model_validate(station, from_attributes=True),
        connectors=[ConnectorResponse.model_validate(c, from_attributes=True) for c in connectors]
    )
    
    if current_transaction:
        response.current_transaction = TransactionBasicInfo.model_validate(current_transaction, from_attributes=True)
    
    return response

@router.put("/{charger_id}", response_model=dict)
async def update_charger(charger_id: int, update_data: ChargerUpdate):
    """Update charger information"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Update only provided fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(charger, field, value)
    
    await charger.save()
    
    # Get connection status for response
    connection_status_dict = await get_bulk_connection_status([charger])
    connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
    return {
        "charger": charger_to_response(charger, connection_status),
        "message": "Charger updated successfully"
    }

@router.delete("/{charger_id}", response_model=dict)
async def delete_charger(charger_id: int):
    """Remove a charger from the system"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Delete charger (connectors will cascade)
    await charger.delete()
    
    return {"message": "Charger removed successfully"}

@router.post("/{charger_id}/remote-stop", response_model=dict)
async def remote_stop_charging(charger_id: int, reason: Optional[str] = "Requested by operator"):
    """Stop charging remotely"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Get connected charge points
    connected_cps = get_connected_charge_points()
    
    if charger.charge_point_string_id not in connected_cps:
        raise HTTPException(status_code=409, detail="Charger is not connected")
    
    # Import and use the send_ocpp_request function
    from main import send_ocpp_request
    
    # Get active transaction
    transaction = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "RUNNING"]
    ).first()
    
    if not transaction:
        raise HTTPException(status_code=409, detail="No active charging session found")
    
    # Send RemoteStopTransaction command
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStopTransaction",
        {"transactionId": transaction.id}
    )
    
    if success:
        return {
            "success": True,
            "message": "Stop command sent successfully",
            "transaction_id": str(transaction.id)
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send stop command: {response}")

@router.post("/{charger_id}/change-availability", response_model=dict)
async def change_charger_availability(
    charger_id: int,
    type: str = Query(..., regex="^(Inoperative|Operative)$"),
    connector_id: int = Query(..., ge=0)
):
    """Change charger availability (Operative/Inoperative)"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Get connected charge points
    connected_cps = get_connected_charge_points()
    
    if charger.charge_point_string_id not in connected_cps:
        raise HTTPException(status_code=409, detail="Charger is not connected")
    
    # Import and use the send_ocpp_request function
    from main import send_ocpp_request
    
    # Send ChangeAvailability command
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "ChangeAvailability",
        {
            "connectorId": connector_id,
            "type": type
        }
    )
    
    if success:
        return {
            "success": True,
            "message": f"Availability changed to {type} successfully"
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to change availability: {response}")

@router.get("/{charger_id}/logs", response_model=LogsListResponse)
async def get_charger_logs(
    charger_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    direction: Optional[str] = Query(None, regex="^(IN|OUT)$"),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    """Get OCPP communication logs for a specific charger"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Build query
    query = OCPPLog.filter(charge_point_id=charger.charge_point_string_id)
    
    # Apply filters
    if direction:
        query = query.filter(direction=direction)
    if start_date:
        query = query.filter(timestamp__gte=start_date)
    if end_date:
        query = query.filter(timestamp__lte=end_date)
    
    # Get total count
    total = await query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    logs = await query.order_by("-timestamp").offset(offset).limit(limit)
    
    log_responses = [OCPPLogResponse.model_validate(log, from_attributes=True) for log in logs]
    
    return LogsListResponse(
        data=log_responses,
        total=total,
        page=page,
        limit=limit
    )