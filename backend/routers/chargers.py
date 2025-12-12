# routers/chargers.py
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from datetime import datetime
import uuid
import logging

from models import Charger, ChargingStation, Connector, Transaction, OCPPLog, User
from tortoise.exceptions import IntegrityError
from auth_middleware import require_admin, require_user_or_admin

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
    firmware_version: Optional[str]
    latest_status: str
    last_heart_beat_time: Optional[datetime]
    connection_status: bool
    created_at: datetime
    updated_at: datetime
    tariff_per_kwh: Optional[float] = None

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

class CurrentTransactionInfo(BaseModel):
    transaction_id: int
    
    class Config:
        from_attributes = True

class ChargerDetailResponse(BaseModel):
    charger: ChargerResponse
    station: StationBasicInfo
    connectors: List[ConnectorResponse]
    current_transaction: Optional[CurrentTransactionInfo] = None
    recent_transaction: Optional[CurrentTransactionInfo] = None

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
    
    from datetime import timezone
    current_time = datetime.now(timezone.utc)
    status_dict = {}
    
    for charger in chargers:
        # Check Redis connection first
        is_connected_redis = charger.charge_point_string_id in connected_charger_ids
        if not is_connected_redis:
            status_dict[charger.charge_point_string_id] = False
            continue
        
        # Check heartbeat timeout (90 seconds)
        if not charger.last_heart_beat_time:
            status_dict[charger.charge_point_string_id] = False
            continue

        time_diff = current_time - charger.last_heart_beat_time
        status_dict[charger.charge_point_string_id] = time_diff.total_seconds() <= 90
    
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
        firmware_version=charger.firmware_version,
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
    sort: Optional[str] = Query("created_at", regex="^(created_at|updated_at|name|latest_status)$"),
    admin_user: User = Depends(require_admin())
):
    """List all chargers with filtering options (admin only)"""
    
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
async def create_charger(charger_data: ChargerCreate, admin_user: User = Depends(require_admin())):
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
            latest_status="Unavailable"
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
async def get_charger_details(charger_id: int, user: User = Depends(require_user_or_admin())):
    """Get detailed charger information (accessible by users and admins)"""


    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Get related data
    station = await ChargingStation.filter(id=charger.station_id).first()
    connectors = await Connector.filter(charger_id=charger_id).all()

    # Get applicable tariff for this charger
    from services.wallet_service import WalletService
    tariff_rate = await WalletService.get_applicable_tariff(charger_id)

    # Get current active transaction if any
    current_transaction = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
    ).first()

    # If no active transaction, get the most recent completed transaction (within last 5 minutes)
    # This helps users see billing info after remote stops by admin
    recent_transaction = None
    if not current_transaction:
        from datetime import datetime, timezone, timedelta
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_transaction = await Transaction.filter(
            charger_id=charger_id,
            transaction_status__in=["COMPLETED", "STOPPED", "BILLING_FAILED", "FAILED"],
            end_time__gte=five_minutes_ago
        ).order_by('-end_time').first()

    # Get connection status
    connection_status_dict = await get_bulk_connection_status([charger])
    connection_status = connection_status_dict.get(charger.charge_point_string_id, False)

    # Build charger response with tariff
    charger_response = charger_to_response(charger, connection_status)
    charger_dict = charger_response.model_dump()
    charger_dict['tariff_per_kwh'] = float(tariff_rate) if tariff_rate else None

    # Build response
    response = ChargerDetailResponse(
        charger=ChargerResponse(**charger_dict),
        station=StationBasicInfo.model_validate(station, from_attributes=True),
        connectors=[ConnectorResponse.model_validate(c, from_attributes=True) for c in connectors]
    )
    
    # Set current transaction only if truly active
    if current_transaction:
        response.current_transaction = CurrentTransactionInfo(transaction_id=current_transaction.id)
    
    # Set recent transaction separately (for billing display after completion)
    if recent_transaction:
        response.recent_transaction = CurrentTransactionInfo(transaction_id=recent_transaction.id)
    
    return response

@router.put("/{charger_id}", response_model=dict)
async def update_charger(charger_id: int, update_data: ChargerUpdate, admin_user: User = Depends(require_admin())):
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
async def delete_charger(charger_id: int, admin_user: User = Depends(require_admin())):
    """Remove a charger from the system"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Delete charger (connectors will cascade)
    await charger.delete()
    
    return {"message": "Charger removed successfully"}

@router.post("/{charger_id}/remote-start", response_model=dict)
async def remote_start_charging(charger_id: int, connector_id: int = 1, user: User = Depends(require_user_or_admin())):
    """Start charging remotely"""
    
    # Use the user's RFID card ID as idTag for OCPP identification
    if not user.rfid_card_id:
        raise HTTPException(status_code=409, detail="User does not have an RFID card ID assigned")
    
    actual_id_tag = user.rfid_card_id
    logger.info(f"🚀 Remote start requested by user {user.clerk_user_id} (role: {user.role}) using idTag: {actual_id_tag}")
    
    # FIXME: connector_id is hardcoded to 1 - should dynamically select available connector
    # or allow user to choose from available connectors for this charger
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Check if charger status is suitable for remote start
    if charger.latest_status != "Preparing":
        raise HTTPException(status_code=409, detail=f"Cannot start charging. Charger status is {charger.latest_status}, should be Preparing")
    
    # Get connected charge points
    connected_cps = get_connected_charge_points()
    
    if charger.charge_point_string_id not in connected_cps:
        raise HTTPException(status_code=409, detail="Charger is not connected")
    
    # Check if there's already an active transaction
    existing_transaction = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
    ).first()
    
    if existing_transaction:
        raise HTTPException(status_code=409, detail="There is already an active charging session")
    
    # Import and use the send_ocpp_request function
    from main import send_ocpp_request
    
    # Send RemoteStartTransaction command with authenticated user's clerk ID
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStartTransaction",
        {
            "connector_id": connector_id,
            "id_tag": actual_id_tag  # Use authenticated user's RFID card ID
        }
    )
    
    if success:
        return {
            "success": True,
            "message": "Remote start command sent successfully",
            "connector_id": connector_id
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send start command: {response}")

@router.post("/{charger_id}/remote-stop", response_model=dict)
async def remote_stop_charging(charger_id: int, reason: Optional[str] = "Requested by operator", user: User = Depends(require_user_or_admin())):
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
    
    # Security check: Only transaction owner or admin can stop the session
    from models import UserRoleEnum
    is_admin = user.role == UserRoleEnum.ADMIN
    is_owner = transaction.user_id == user.id
    
    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=403, 
            detail="You can only stop your own charging sessions"
        )
    
    # Log admin override for audit trail
    if is_admin and not is_owner:
        logger.info(f"🛡️ Admin {user.email} stopping transaction {transaction.id} belonging to user {transaction.user_id}")
    
    # Send RemoteStopTransaction command
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStopTransaction",
        {"transaction_id": transaction.id}
    )
    
    if success:
        action_type = "Admin override stop" if is_admin and not is_owner else "Remote stop"
        return {
            "success": True,
            "message": f"{action_type} command sent successfully",
            "transaction_id": transaction.id,
            "charger_id": charger_id,
            "transaction_owner": transaction.user_id,
            "stopped_by": user.id
        }
    else:
        # Don't modify transaction state - let user know the command failed
        error_msg = f"Failed to send stop command to charger: {response}"
        logger.warning(f"Remote stop failed for transaction {transaction.id}: {error_msg}")
        raise HTTPException(
            status_code=409, 
            detail=f"Unable to stop charging session. {error_msg}. Please try again or contact support."
        )

@router.post("/{charger_id}/change-availability", response_model=dict)
async def change_charger_availability(
    charger_id: int,
    type: str = Query(..., regex="^(Inoperative|Operative)$"),
    connector_id: int = Query(..., ge=0),
    admin_user: User = Depends(require_admin())
):
    """Change charger availability (Operative/Inoperative) - OCPP 1.6 compliant"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # OCPP 1.6 Compliance: Validate state transitions
    current_status = charger.latest_status
    
    if type == "Inoperative":
        # Can only set to Inoperative if currently Available
        if current_status != "Available":
            raise HTTPException(
                status_code=409, 
                detail=f"Cannot set charger to Inoperative. Current status is '{current_status}'. Only 'Available' chargers can be made Inoperative."
            )
    elif type == "Operative":
        # Can only set to Operative if currently Unavailable
        if current_status != "Unavailable":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot set charger to Operative. Current status is '{current_status}'. Only 'Unavailable' chargers can be made Operative."
            )
    
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
            "connector_id": connector_id,
            "type": type
        }
    )
    
    if success:
        return {
            "success": True,
            "message": f"Availability changed to {type} successfully",
            "previous_status": current_status,
            "expected_new_status": "Available" if type == "Operative" else "Unavailable"
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to change availability: {response}")

@router.post("/{charger_id}/reset", response_model=dict)
async def reset_charger(
    charger_id: int,
    type: str = Query("Hard", regex="^(Hard|Soft)$"),
    admin_user: User = Depends(require_admin())
):
    """
    Reset charger remotely - OCPP 1.6 compliant

    - Hard: Complete reboot of the charger (stops active transactions)
    - Soft: Graceful restart (may continue operating or restart gracefully)

    Hard reset is blocked if there's an active charging session.
    """

    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Check for active transactions if Hard reset
    if type == "Hard":
        active_transaction = await Transaction.filter(
            charger_id=charger_id,
            transaction_status__in=["RUNNING", "STARTED", "PENDING_START"]
        ).first()

        if active_transaction:
            raise HTTPException(
                status_code=409,
                detail="Cannot perform Hard reset while charging is active. Please stop the transaction first or use Soft reset."
            )

    # Get connected charge points
    connected_cps = get_connected_charge_points()

    if charger.charge_point_string_id not in connected_cps:
        raise HTTPException(status_code=409, detail="Charger is not connected")

    # Import and use the send_ocpp_request function
    from main import send_ocpp_request

    # Send Reset command
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "Reset",
        {"type": type}
    )

    if success:
        return {
            "success": True,
            "message": f"{type} reset command sent successfully",
            "reset_type": type,
            "charger_id": charger_id
        }
    else:
        raise HTTPException(status_code=500, detail=f"Failed to send reset command: {response}")

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

# ============ Signal Quality Endpoints ============

class SignalQualityResponse(BaseModel):
    """Response schema for signal quality data point"""
    id: int
    charger_id: int
    rssi: int  # Received Signal Strength Indicator (0-31 for GSM, 99=unknown)
    ber: int   # Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
    timestamp: str
    created_at: datetime

    class Config:
        from_attributes = True

class SignalQualityListResponse(BaseModel):
    """Response schema for list of signal quality data"""
    data: List[SignalQualityResponse]
    total: int
    page: int
    limit: int
    charger_id: int
    latest_rssi: Optional[int] = None
    latest_ber: Optional[int] = None

@router.get("/{charger_id}/signal-quality", response_model=SignalQualityListResponse)
async def get_charger_signal_quality(
    charger_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    hours: int = Query(24, ge=1, le=720, description="Number of hours of history to retrieve (max 30 days)"),
    admin_user: User = Depends(require_admin())
):
    """
    Get signal quality history for a specific charger (Admin only)

    Returns paginated signal quality data for the specified charger.
    Data includes RSSI (signal strength) and BER (bit error rate) metrics.
    """
    from models import SignalQuality
    from datetime import datetime, timedelta

    # Verify charger exists
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Calculate cutoff time
    cutoff_time = datetime.utcnow() - timedelta(hours=hours)

    # Build query
    query = SignalQuality.filter(
        charger_id=charger_id,
        created_at__gte=cutoff_time
    )

    # Get total count
    total = await query.count()

    # Apply pagination
    offset = (page - 1) * limit
    signal_data = await query.order_by("-created_at").offset(offset).limit(limit)

    # Get latest values (most recent record)
    latest = await SignalQuality.filter(charger_id=charger_id).order_by("-created_at").first()
    latest_rssi = latest.rssi if latest else None
    latest_ber = latest.ber if latest else None

    # Convert to response models
    data_responses = [SignalQualityResponse.model_validate(d, from_attributes=True) for d in signal_data]

    return SignalQualityListResponse(
        data=data_responses,
        total=total,
        page=page,
        limit=limit,
        charger_id=charger_id,
        latest_rssi=latest_rssi,
        latest_ber=latest_ber
    )

@router.get("/{charger_id}/signal-quality/latest", response_model=Optional[SignalQualityResponse])
async def get_charger_latest_signal_quality(
    charger_id: int,
    admin_user: User = Depends(require_admin())
):
    """
    Get the most recent signal quality reading for a specific charger (Admin only)

    Returns the latest RSSI and BER values, or null if no data available.
    """
    from models import SignalQuality

    # Verify charger exists
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Get most recent signal quality record
    latest = await SignalQuality.filter(charger_id=charger_id).order_by("-created_at").first()

    if not latest:
        return None

    return SignalQualityResponse.model_validate(latest, from_attributes=True)