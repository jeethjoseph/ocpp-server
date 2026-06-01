# routers/chargers.py
from decimal import Decimal
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
import uuid
import logging

from core.config import RAZORPAY_PLATFORM_FEE_PERCENT
from models import Charger, ChargingStation, Connector, Transaction, OCPPLog, User, ChargerError, Tariff
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction
from auth_middleware import require_admin, require_user_or_admin
from crud import log_audit_event
from services.tariff_utils import back_derive_rate_per_kwh

logger = logging.getLogger(__name__)

# Pydantic schemas
class ConnectorInput(BaseModel):
    connector_id: int
    connector_type: str
    max_power_kw: Optional[float] = None

class ChargerCreate(BaseModel):
    """ADR 0003: tariff is operator-typed as the all-inclusive per-kWh rate
    (`tariff_per_kwh_all_in`). The legacy `tariff_per_kwh` / `tariff_per_kwh_incl_tax`
    request fields are rejected via `extra='forbid'`."""
    model_config = {"extra": "forbid"}

    station_id: int
    name: str
    model: Optional[str] = None
    vendor: Optional[str] = None
    serial_number: Optional[str] = None
    external_charger_id: Optional[str] = None
    connectors: List[ConnectorInput]
    tariff_per_kwh_all_in: Optional[float] = Field(
        None, ge=1.0, le=100.0,
        description="All-inclusive per-kWh tariff (incl. GST + 2% gateway fee). 1.0–100.0.",
    )


class ChargerUpdate(BaseModel):
    """ADR 0003: see ChargerCreate."""
    model_config = {"extra": "forbid"}

    name: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None
    latest_status: Optional[str] = None
    external_charger_id: Optional[str] = None
    tariff_per_kwh_all_in: Optional[float] = Field(
        None, ge=1.0, le=100.0,
        description="All-inclusive per-kWh tariff (incl. GST + 2% gateway fee). 1.0–100.0.",
    )

class LatestErrorInfo(BaseModel):
    """Summary of latest unresolved error for a charger"""
    error_code: str
    vendor_error_code: Optional[str] = None
    info: Optional[str] = None
    created_at: datetime

class ChargerResponse(BaseModel):
    id: int
    charge_point_string_id: str
    external_charger_id: Optional[str]
    station_id: int
    name: str
    model: Optional[str]
    vendor: Optional[str]
    serial_number: Optional[str]
    firmware_version: Optional[str]
    latest_status: str
    # Admin-set availability ("Operative" | "Inoperative"). Distinct from
    # latest_status — the UI toggle reads THIS field. See ADR 0008.
    availability: str
    last_heart_beat_time: Optional[datetime]
    connection_status: bool
    created_at: datetime
    updated_at: datetime
    tariff_per_kwh: Optional[float] = None  # back-derived; internal billing math
    tariff_gst_percent: Optional[float] = None
    tariff_per_kwh_all_in: Optional[float] = None  # operator-set, customer-displayed
    latest_error: Optional[LatestErrorInfo] = None

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

async def is_charger_connected(charge_point_string_id: str) -> bool:
    """Check if a charger is connected via Redis (works across all workers)"""
    return await redis_manager.is_charger_connected(charge_point_string_id)

async def get_bulk_connection_status(chargers: List[Charger]) -> Dict[str, bool]:
    """Get connection status for multiple chargers efficiently"""
    # Get all connected chargers from Redis at once
    connected_charger_ids = set(await redis_manager.get_all_connected_chargers())
    
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

def charger_to_response(
    charger: Charger,
    connection_status: bool,
    latest_error: Optional[ChargerError] = None,
    tariff: Optional[Tariff] = None,
) -> ChargerResponse:
    """Convert a Charger model to ChargerResponse with connection status, latest error, and tariff"""
    error_info = None
    if latest_error:
        error_info = LatestErrorInfo(
            error_code=latest_error.error_code,
            vendor_error_code=latest_error.vendor_error_code,
            info=latest_error.info,
            created_at=latest_error.created_at
        )

    tariff_rate = float(tariff.rate_per_kwh) if tariff else None
    tariff_gst = float(tariff.gst_percent) if tariff else None
    tariff_all_in = float(tariff.tariff_per_kwh_all_in) if tariff else None

    return ChargerResponse(
        id=charger.id,
        charge_point_string_id=charger.charge_point_string_id,
        external_charger_id=charger.external_charger_id,
        station_id=charger.station_id,
        name=charger.name,
        model=charger.model,
        vendor=charger.vendor,
        serial_number=charger.serial_number,
        firmware_version=charger.firmware_version,
        latest_status=charger.latest_status,
        availability=(
            charger.availability.value
            if hasattr(charger.availability, "value")
            else str(charger.availability)
        ),
        last_heart_beat_time=charger.last_heart_beat_time,
        created_at=charger.created_at,
        updated_at=charger.updated_at,
        connection_status=connection_status,
        latest_error=error_info,
        tariff_per_kwh=tariff_rate,
        tariff_gst_percent=tariff_gst,
        tariff_per_kwh_all_in=tariff_all_in,
    )


async def get_applicable_tariffs_for_chargers(charger_ids: List[int]) -> Dict[int, Tariff]:
    """Bulk-resolve the applicable tariff for each charger.
    Priority: charger-specific tariff -> global tariff."""
    if not charger_ids:
        return {}

    specific = await Tariff.filter(charger_id__in=charger_ids)
    by_charger = {t.charger_id: t for t in specific}

    missing = [cid for cid in charger_ids if cid not in by_charger]
    if missing:
        global_tariff = await Tariff.filter(is_global=True).first()
        if global_tariff:
            for cid in missing:
                by_charger[cid] = global_tariff

    return by_charger

async def get_latest_errors_for_chargers(charger_ids: List[int]) -> Dict[int, ChargerError]:
    """Get the latest unresolved error for multiple chargers efficiently"""
    if not charger_ids:
        return {}

    # Get latest unresolved error for each charger
    errors = await ChargerError.filter(
        charger_id__in=charger_ids,
        is_resolved=False
    ).order_by("-created_at")

    # Group by charger_id and take the first (latest) for each
    error_dict = {}
    for error in errors:
        if error.charger_id not in error_dict:
            error_dict[error.charger_id] = error

    return error_dict

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

    # Get latest errors for all chargers
    charger_ids = [c.id for c in chargers]
    error_dict = await get_latest_errors_for_chargers(charger_ids)

    # Bulk-resolve applicable tariff per charger (charger-specific or global fallback)
    tariff_dict = await get_applicable_tariffs_for_chargers(charger_ids)

    # Build response with connection status, errors, and tariff
    charger_responses = []
    for charger in chargers:
        connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
        latest_error = error_dict.get(charger.id)
        tariff = tariff_dict.get(charger.id)
        charger_responses.append(
            charger_to_response(charger, connection_status, latest_error, tariff)
        )

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
        # All three writes (Charger + Connectors + Tariff) must succeed or fail
        # together — otherwise a partial-failure scenario leaves an orphan
        # charger row with no connectors or no tariff. Issue 05 / M6.
        # Audit log stays OUTSIDE the transaction so the "we attempted this"
        # trail is preserved even on rollback.
        async with in_transaction():
            charger = await Charger.create(
                charge_point_string_id=charge_point_id,
                external_charger_id=charger_data.external_charger_id,
                station_id=charger_data.station_id,
                name=charger_data.name,
                model=charger_data.model,
                vendor=charger_data.vendor,
                serial_number=charger_data.serial_number,
                latest_status="Unavailable"
            )

            for connector_input in charger_data.connectors:
                await Connector.create(
                    charger_id=charger.id,
                    connector_id=connector_input.connector_id,
                    connector_type=connector_input.connector_type,
                    max_power_kw=connector_input.max_power_kw
                )

            # Create charger-specific tariff if provided.
            # The operator types the all-inclusive per-kWh rate; we back-derive
            # rate_per_kwh server-side and persist both. ADR 0003.
            if charger_data.tariff_per_kwh_all_in is not None:
                gst_default = Tariff._meta.fields_map["gst_percent"].default
                gst = Decimal(str(gst_default))
                all_in = Decimal(str(charger_data.tariff_per_kwh_all_in))
                rate = back_derive_rate_per_kwh(all_in, gst, RAZORPAY_PLATFORM_FEE_PERCENT)
                await Tariff.create(
                    charger=charger,
                    rate_per_kwh=rate,
                    tariff_per_kwh_all_in=all_in,
                    gst_percent=gst,
                )

        await log_audit_event(
            action="charger.created",
            entity_type="charger",
            entity_id=charger.charge_point_string_id,
            actor_type="admin",
            actor=admin_user,
            changes={"charge_point_string_id": charge_point_id, "station_id": charger_data.station_id, "name": charger_data.name},
        )

        # Generate OCPP URL
        # You should configure this based on your actual domain
        ocpp_url = f"ws://your-domain.com/ocpp/{charge_point_id}"

        # Get connection status for response (new charger won't be connected yet)
        connection_status_dict = await get_bulk_connection_status([charger])
        connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
        applicable_tariff = (await get_applicable_tariffs_for_chargers([charger.id])).get(charger.id)
        return {
            "charger": charger_to_response(charger, connection_status, tariff=applicable_tariff),
            "ocpp_url": ocpp_url,
            "message": "Charger onboarded successfully"
        }
    except IntegrityError as e:
        # The transaction has already rolled back at this point — no Charger /
        # Connector / Tariff row persists. Record the attempt anyway so the
        # audit trail captures "operator tried, system refused" with enough
        # context to debug. Best-effort: a secondary audit failure shouldn't
        # mask the original 400 response.
        try:
            await log_audit_event(
                action="charger.create_failed",
                entity_type="charger",
                entity_id=charge_point_id,
                actor_type="admin",
                actor=admin_user,
                changes={
                    "charge_point_string_id": charge_point_id,
                    "station_id": charger_data.station_id,
                    "name": charger_data.name,
                    "failure_reason": str(e),
                },
            )
        except Exception as audit_err:
            logger.warning(
                "Failed to write rollback audit for charger create attempt %s: %s",
                charge_point_id, audit_err,
            )
        raise HTTPException(status_code=400, detail="Charger creation failed - check serial number or external charger ID uniqueness")

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
    tariff = await WalletService.get_applicable_tariff(charger_id)

    # Get current active transaction if any
    current_transaction = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
    ).first()

    # If no active transaction, get the most recent completed transaction (within last 5 minutes)
    # This helps users see billing info after remote stops by admin
    recent_transaction = None
    if not current_transaction:
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_transaction = await Transaction.filter(
            charger_id=charger_id,
            transaction_status__in=["COMPLETED", "STOPPED", "BILLING_FAILED", "FAILED"],
            end_time__gte=five_minutes_ago
        ).order_by('-end_time').first()

    # Get connection status
    connection_status_dict = await get_bulk_connection_status([charger])
    connection_status = connection_status_dict.get(charger.charge_point_string_id, False)

    # Get latest unresolved error
    latest_error = await ChargerError.filter(
        charger_id=charger_id,
        is_resolved=False
    ).order_by("-created_at").first()

    # Build charger response with tariff and error
    charger_response = charger_to_response(charger, connection_status, latest_error, tariff)

    # Build response
    response = ChargerDetailResponse(
        charger=charger_response,
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

    # Check if external_charger_id is being updated and validate uniqueness
    if update_data.external_charger_id is not None:
        existing = await Charger.filter(
            external_charger_id=update_data.external_charger_id
        ).exclude(id=charger_id).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="External charger ID already exists"
            )

    # Update only provided fields
    update_dict = update_data.model_dump(exclude_unset=True)

    # Tariff is handled out-of-band — back-derive rate_per_kwh from the
    # operator-typed all-in value and persist both columns. ADR 0003.
    tariff_per_kwh_all_in = update_dict.pop("tariff_per_kwh_all_in", None)
    if tariff_per_kwh_all_in is not None:
        existing = await Tariff.filter(charger_id=charger_id).first()
        if existing:
            gst = existing.gst_percent
        else:
            gst_default = Tariff._meta.fields_map["gst_percent"].default
            gst = Decimal(str(gst_default))
        all_in = Decimal(str(tariff_per_kwh_all_in))
        rate = back_derive_rate_per_kwh(all_in, gst, RAZORPAY_PLATFORM_FEE_PERCENT)
        await Tariff.update_or_create(
            defaults={
                "rate_per_kwh": rate,
                "tariff_per_kwh_all_in": all_in,
                "gst_percent": gst,
            },
            charger_id=charger_id,
        )

    for field, value in update_dict.items():
        setattr(charger, field, value)

    try:
        await charger.save()
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Update failed - check external charger ID uniqueness")

    await log_audit_event(
        action="charger.updated",
        entity_type="charger",
        entity_id=charger.charge_point_string_id,
        actor_type="admin",
        actor=admin_user,
        changes=update_dict,
    )

    # Get connection status for response
    connection_status_dict = await get_bulk_connection_status([charger])
    connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
    applicable_tariff = (await get_applicable_tariffs_for_chargers([charger.id])).get(charger.id)
    return {
        "charger": charger_to_response(charger, connection_status, tariff=applicable_tariff),
        "message": "Charger updated successfully"
    }

@router.delete("/{charger_id}", response_model=dict)
async def delete_charger(charger_id: int, admin_user: User = Depends(require_admin())):
    """Remove a charger from the system"""
    
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    charge_point_string_id = charger.charge_point_string_id

    # Delete charger (connectors will cascade)
    await charger.delete()

    await log_audit_event(
        action="charger.deleted",
        entity_type="charger",
        entity_id=charge_point_string_id,
        actor_type="admin",
        actor=admin_user,
        changes={"charge_point_string_id": charge_point_string_id},
    )

    return {"message": "Charger removed successfully"}

@router.post("/{charger_id}/remote-start", response_model=dict)
async def remote_start_charging(charger_id: int, connector_id: int = 1, user: User = Depends(require_user_or_admin())):
    """Start charging remotely"""
    
    # Use the user's RFID card ID as idTag for OCPP identification
    if not user.rfid_card_id:
        raise HTTPException(status_code=409, detail="User does not have an RFID card ID assigned")
    
    actual_id_tag = user.rfid_card_id
    logger.info(f"🚀 Remote start requested by user {user.clerk_user_id} (role: {user.role}) using idTag: {actual_id_tag}")
    
    # connector_id=1 covers all single-connector chargers currently in the fleet.
    # Multi-connector support (user selection of connector) is out of scope for v1.

    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Check if charger status is suitable for remote start
    # Socket chargers may not transition to Preparing (no CP signal), allow Available
    from services.charger_type_service import is_socket_charger
    charger_is_socket = await is_socket_charger(charger.charge_point_string_id)
    allowed_statuses = {"Preparing", "Available"} if charger_is_socket else {"Preparing"}
    if charger.latest_status not in allowed_statuses:
        expected = "Preparing or Available" if charger_is_socket else "Preparing"
        raise HTTPException(status_code=409, detail=f"Cannot start charging. Charger status is {charger.latest_status}, should be {expected}")
    
    # Check if charger is connected (via Redis - works across all workers)
    if not await is_charger_connected(charger.charge_point_string_id):
        raise HTTPException(status_code=409, detail="Charger is not connected")

    # Check if there's already an active transaction
    existing_transaction = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"]
    ).first()
    
    if existing_transaction:
        logger.warning(f"🚫 Blocking remote start: existing transaction id={existing_transaction.id}, "
                      f"status={existing_transaction.transaction_status}, charger_id={existing_transaction.charger_id}, "
                      f"created_at={existing_transaction.created_at}")
        raise HTTPException(status_code=409, detail=f"There is already an active charging session (transaction {existing_transaction.id}, status: {existing_transaction.transaction_status})")
    
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
    
    # Check if charger is connected (via Redis - works across all workers)
    if not await is_charger_connected(charger.charge_point_string_id):
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
    connector_id: int = Query(..., ge=0,
        description="Must be 0 — admin operates at whole-charger granularity. See docstring."),
    admin_user: User = Depends(require_admin())
):
    """
    Change charger availability (Operative/Inoperative) — OCPP 1.6 compliant.

    Per OCPP 1.6 spec, ChangeAvailability can be sent at any time. The charger
    responds with:
    - Accepted: Change applied immediately
    - Scheduled: Will change after current transaction ends
    - Rejected: Cannot comply (e.g., hardware fault)

    Contract notes:
    - `connector_id` must be 0 (whole-charger semantic per OCPP 1.6). The
      admin UI doesn't expose per-connector control; the validator rejects
      anything else with 422 so a curl/ops typo doesn't send a doomed
      OCPP message. If per-connector toggle becomes a product feature later,
      relax the ceiling and add the UI affordance together.
    - `type` uses OCPP vocabulary (Operative/Inoperative). The parallel
      franchisee endpoint at `routers/franchisee_portal.change_availability`
      uses a `?available=bool` query param instead — this divergence is
      intentional (admins are debugging an OCPP layer; franchisees want a
      self-serve boolean). See docs/v1/comprehensive-architecture-documentation.md
      "Charger control surface" for the rationale; do not unify them blindly.
    """

    # Whole-charger semantics only — see contract notes in docstring. Explicit
    # check (not a Pydantic le=0) so the 422 message names the constraint
    # instead of "Input should be less than or equal to 0".
    if connector_id != 0:
        raise HTTPException(
            status_code=422,
            detail=(
                "connector_id must be 0 — admin availability toggle operates "
                "at whole-charger granularity. Per-connector control is not "
                "exposed via the admin API."
            ),
        )

    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Snapshot the charger's state at the moment the operator clicked. This is
    # captured BEFORE the OCPP exchange so `previous_status` reflects "what
    # was the charger doing when the operator pressed the button" — the right
    # audit semantic. (An earlier revision read it AFTER the exchange; that
    # broke the field's meaning whenever the charger Accepted and immediately
    # fired a StatusNotification reflecting the new state.)
    current_status = charger.latest_status

    # Check if charger is connected (via Redis - works across all workers)
    if not await is_charger_connected(charger.charge_point_string_id):
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
        # Get the OCPP response status (Accepted/Scheduled/Rejected)
        ocpp_status = getattr(response, 'status', str(response))

        # Persist admin intent when the charger acknowledged the command.
        # See ADR 0008 for why availability is separate from latest_status.
        from models import ChargerAvailabilityEnum
        new_availability = None
        if ocpp_status in ("Accepted", "Scheduled"):
            new_availability = (
                ChargerAvailabilityEnum.OPERATIVE
                if type == "Operative"
                else ChargerAvailabilityEnum.INOPERATIVE
            )
            await Charger.filter(id=charger_id).update(availability=new_availability)

        await log_audit_event(
            action="charger.availability_changed",
            entity_type="charger",
            entity_id=charger.charge_point_string_id,
            actor_type="admin",
            actor=admin_user,
            changes={
                "type": type,
                "connector_id": connector_id,
                "ocpp_response": ocpp_status,
                "previous_status": current_status,
                "new_availability": new_availability.value if new_availability else None,
            },
        )

        return {
            "success": True,
            "message": f"ChangeAvailability command sent",
            "ocpp_response": ocpp_status,
            "type": type,
            "previous_status": current_status,
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

    # Check if charger is connected (via Redis - works across all workers)
    if not await is_charger_connected(charger.charge_point_string_id):
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
        await log_audit_event(
            action="charger.reset",
            entity_type="charger",
            entity_id=charger.charge_point_string_id,
            actor_type="admin",
            actor=admin_user,
            changes={"reset_type": type},
        )

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
    """Response schema for a signal-quality / modem-telemetry data point.

    Despite the legacy ``signal_quality`` table name, the row also carries
    modem board temperature (see ADR 0009). ``temperature_celsius`` is null
    for rows captured before the temperature column was added (migration 43)
    or for chargers on firmware that doesn't yet emit the field.
    """
    id: int
    charger_id: int
    rssi: int  # Received Signal Strength Indicator (0-31 for GSM, 99=unknown)
    ber: int   # Bit Error Rate (0-7 for GSM, 99=unknown/not detectable)
    temperature_celsius: Optional[float] = None  # Modem board temperature
    timestamp: str
    created_at: datetime

    class Config:
        from_attributes = True

class SignalQualityListResponse(BaseModel):
    """Response schema for list of signal quality / modem telemetry data."""
    data: List[SignalQualityResponse]
    total: int
    page: int
    limit: int
    charger_id: int
    latest_rssi: Optional[int] = None
    latest_ber: Optional[int] = None
    latest_temperature_celsius: Optional[float] = None

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

    # Verify charger exists
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Calculate cutoff time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

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
    latest_temperature_celsius = latest.temperature_celsius if latest else None

    # Convert to response models
    data_responses = [SignalQualityResponse.model_validate(d, from_attributes=True) for d in signal_data]

    return SignalQualityListResponse(
        data=data_responses,
        total=total,
        page=page,
        limit=limit,
        charger_id=charger_id,
        latest_rssi=latest_rssi,
        latest_ber=latest_ber,
        latest_temperature_celsius=latest_temperature_celsius,
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

# ============ Charger Error Endpoints ============

class ChargerErrorResponse(BaseModel):
    """Response schema for charger error data"""
    id: int
    charger_id: int
    connector_id: int
    status: str
    error_code: str
    vendor_error_code: Optional[str] = None
    vendor_id: Optional[str] = None
    info: Optional[str] = None
    error_timestamp: Optional[datetime] = None
    is_resolved: bool
    resolved_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ChargerErrorListResponse(BaseModel):
    """Response schema for list of charger errors"""
    data: List[ChargerErrorResponse]
    total: int
    page: int
    limit: int
    charger_id: int
    unresolved_count: int

@router.get("/{charger_id}/errors", response_model=ChargerErrorListResponse)
async def get_charger_errors(
    charger_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    include_resolved: bool = Query(True, description="Include resolved errors"),
    hours: int = Query(168, ge=1, le=2160, description="Hours of history (max 90 days)"),
    admin_user: User = Depends(require_admin())
):
    """
    Get error history for a specific charger (Admin only)

    Returns paginated error data including both standard OCPP error codes
    and vendor-specific error codes.
    """
    # Verify charger exists
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Calculate cutoff time
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Build query
    query = ChargerError.filter(
        charger_id=charger_id,
        created_at__gte=cutoff_time
    )

    if not include_resolved:
        query = query.filter(is_resolved=False)

    # Get total count
    total = await query.count()

    # Get unresolved count
    unresolved_count = await ChargerError.filter(
        charger_id=charger_id,
        is_resolved=False
    ).count()

    # Apply pagination
    offset = (page - 1) * limit
    errors = await query.order_by("-created_at").offset(offset).limit(limit)

    # Convert to response models
    data_responses = [ChargerErrorResponse.model_validate(e, from_attributes=True) for e in errors]

    return ChargerErrorListResponse(
        data=data_responses,
        total=total,
        page=page,
        limit=limit,
        charger_id=charger_id,
        unresolved_count=unresolved_count
    )

@router.get("/{charger_id}/errors/latest", response_model=Optional[ChargerErrorResponse])
async def get_charger_latest_error(
    charger_id: int,
    admin_user: User = Depends(require_admin())
):
    """
    Get the most recent unresolved error for a specific charger (Admin only)

    Returns the latest error, or null if no unresolved errors.
    """
    # Verify charger exists
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Get most recent unresolved error
    latest = await ChargerError.filter(
        charger_id=charger_id,
        is_resolved=False
    ).order_by("-created_at").first()

    if not latest:
        return None

    return ChargerErrorResponse.model_validate(latest, from_attributes=True)