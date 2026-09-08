# routers/chargers.py
from decimal import Decimal
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
import uuid
import logging

from core.config import wallet_charging_enabled
from core.roles import INTERNAL_ROLES
from models import Charger, ChargingStation, Connector, ConnectorTypeEnum, Transaction, OCPPLog, User, ChargerError, Tariff, ChargerPurposeEnum
from tortoise.expressions import Q
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction
from auth_middleware import require_admin, require_user_or_admin
from crud import log_audit_event
from services.tariff_utils import back_calc_base_rate
from services.charger_type_service import canonical_connector_type
from services import charger_auth_service, charger_code_service

logger = logging.getLogger(__name__)

# Pydantic schemas
class ConnectorInput(BaseModel):
    connector_id: int
    connector_type: str
    max_power_kw: Optional[float] = None

class ChargerCreate(BaseModel):
    """ADR 0026: tariff is operator-typed as the GST-inclusive, gateway-exclusive
    per-kWh rate (`rate_gst_included`). Legacy tariff request fields are rejected
    via `extra='forbid'`."""
    model_config = {"extra": "forbid"}

    station_id: int
    name: str
    model: Optional[str] = None
    vendor: Optional[str] = None
    serial_number: Optional[str] = None
    external_charger_id: Optional[str] = None
    connectors: List[ConnectorInput]
    rate_gst_included: Optional[float] = Field(
        None, ge=1.0, le=100.0,
        description="GST-inclusive, gateway-exclusive per-kWh tariff. 1.0–100.0. See ADR 0026.",
    )


# Selectable connector types for the admin Charger forms — derived from the
# canonical enum. Physical behavior per type (start gate, suspend window) is
# declared in services.charger_type_service.CONNECTOR_TRAITS. Validation and
# canonicalization ("type 2" -> "Type2") go through canonical_connector_type.
ALLOWED_CONNECTOR_TYPES = [m.value for m in ConnectorTypeEnum]


class ChargerUpdate(BaseModel):
    """ADR 0003: see ChargerCreate."""
    model_config = {"extra": "forbid"}

    name: Optional[str] = None
    model: Optional[str] = None
    vendor: Optional[str] = None
    latest_status: Optional[str] = None
    external_charger_id: Optional[str] = None
    # Connector type drives socket-vs-tethered behaviour (start-from-Available).
    # Editable so an admin can correct a mis-provisioned charger. Validated
    # against ALLOWED_CONNECTOR_TYPES; applied to the charger's connector(s).
    connector_type: Optional[str] = None
    rate_gst_included: Optional[float] = Field(
        None, ge=1.0, le=100.0,
        description="GST-inclusive, gateway-exclusive per-kWh tariff. 1.0–100.0. See ADR 0026.",
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
    # The customer-facing Asset Code (ADR 0028). Admin surfaces show it
    # alongside charge_point_string_id, which stays visible here because ops
    # needs the OCPP identity for log correlation and firmware deploys.
    asset_code: Optional[str]
    # Serviceability: PUBLIC | TEST. Drives the TEST badge in the admin UI.
    purpose: str
    last_heart_beat_time: Optional[datetime]
    connection_status: bool
    # Whether a Charger Auth Key has been provisioned. A boolean, never the hash
    # — it exists so the UI can tell "Generate" from "Rotate" *before* the
    # destructive call, which is the signal whose absence made an accidental
    # rotation possible at all.
    has_auth_key: bool
    created_at: datetime
    updated_at: datetime
    tariff_per_kwh: Optional[float] = None  # back-derived; internal billing math
    tariff_gst_percent: Optional[float] = None
    rate_gst_included: Optional[float] = None  # operator-set, customer-displayed (GST-incl, gateway-excl)
    latest_error: Optional[LatestErrorInfo] = None
    connectors: List["ConnectorResponse"] = []

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

# ChargerResponse.connectors forward-references ConnectorResponse (defined above);
# resolve the ref now that it exists.
ChargerResponse.model_rebuild()

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
    connectors: Optional[List["Connector"]] = None,
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
    tariff_gst_incl = float(tariff.rate_gst_included) if tariff else None

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
        asset_code=charger.asset_code,
        purpose=(
            charger.purpose.value
            if hasattr(charger.purpose, "value")
            else str(charger.purpose)
        ),
        last_heart_beat_time=charger.last_heart_beat_time,
        has_auth_key=bool(charger.auth_key_hash),
        created_at=charger.created_at,
        updated_at=charger.updated_at,
        connection_status=connection_status,
        latest_error=error_info,
        tariff_per_kwh=tariff_rate,
        tariff_gst_percent=tariff_gst,
        rate_gst_included=tariff_gst_incl,
        connectors=[
            ConnectorResponse.model_validate(c, from_attributes=True)
            for c in (connectors or [])
        ],
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

def _charger_search_filter(search: str) -> Q:
    """Match a charger by name, OCPP identity, or Asset Code.

    The Asset Code arm resolves by PARSING THE INTEGER rather than matching the
    string, so a customer quoting "VOW1" and an admin pasting "VOW0001" land on
    the same unit. That is what makes ADR 0028's minimum-width rule safe: a
    code typed at one padding resolves at any other, so the register can widen
    past VOW9999 without re-padding anything.

    A FOREIGN SERIES RESOLVES TO NOTHING, never to the local unit with the same
    number. Both registers mint codes a real person reads off a real unit, so
    coercing a staging code into a production lookup would hand support the
    wrong charger — a wrong-answer bug, which is worse than a no-answer one.
    Because `parse_asset_code` returns None for a foreign series, the exact-code
    arm simply contributes no match.
    """
    clauses = Q(name__icontains=search) | Q(charge_point_string_id__icontains=search)

    number = charger_code_service.parse_asset_code(search)
    if number is not None:
        clauses = clauses | Q(
            asset_code=charger_code_service.format_asset_code(number)
        )
    else:
        # Not a resolvable code — still allow substring matching so a partial
        # paste ("VOWS00") narrows the list rather than returning nothing.
        clauses = clauses | Q(asset_code__icontains=search)
    return clauses


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
        query = query.filter(_charger_search_filter(search))
    
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

    # Bulk-load connectors so the list carries connector_type (drives socket
    # classification + the admin Edit form's connector dropdown). One query.
    connectors_dict: Dict[int, List[Connector]] = {}
    if charger_ids:
        for conn in await Connector.filter(charger_id__in=charger_ids):
            connectors_dict.setdefault(conn.charger_id, []).append(conn)

    # Build response with connection status, errors, and tariff
    charger_responses = []
    for charger in chargers:
        connection_status = connection_status_dict.get(charger.charge_point_string_id, False)
        latest_error = error_dict.get(charger.id)
        tariff = tariff_dict.get(charger.id)
        charger_responses.append(
            charger_to_response(
                charger, connection_status, latest_error, tariff,
                connectors=connectors_dict.get(charger.id, []),
            )
        )

    return ChargerListResponse(
        data=charger_responses,
        total=total,
        page=page,
        limit=limit
    )



async def _create_charger_rows(charger_data: "ChargerCreate", canonical_types, charge_point_id: str):
    """Write the Charger, its Connectors and its Tariff as one unit.

    All three writes must succeed or fail together — a partial failure would
    leave an orphan charger row with no connectors or no tariff (issue 05 / M6).
    The audit log deliberately stays OUTSIDE this, so the "operator tried"
    trail survives a rollback.

    No Asset Code handling here on purpose. The code is allocated by the
    `allocate_asset_code` pre_save hook from a Postgres sequence, which is
    concurrency-safe — so there is no collision to retry and no creation path
    that can forget. See ADR 0028.
    """
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

        for connector_input, canonical_type in zip(charger_data.connectors, canonical_types):
            await Connector.create(
                charger_id=charger.id,
                connector_id=connector_input.connector_id,
                connector_type=canonical_type,
                max_power_kw=connector_input.max_power_kw
            )

        # Create charger-specific tariff if provided. The operator types the
        # GST-inclusive, gateway-exclusive rate; we back-calc the base rate
        # server-side and persist both. ADR 0026.
        if charger_data.rate_gst_included is not None:
            gst_default = Tariff._meta.fields_map["gst_percent"].default
            gst = Decimal(str(gst_default))
            gst_incl = Decimal(str(charger_data.rate_gst_included))
            rate = back_calc_base_rate(gst_incl, gst)
            await Tariff.create(
                charger=charger,
                rate_per_kwh=rate,
                rate_gst_included=gst_incl,
                gst_percent=gst,
            )
    return charger


@router.post("", response_model=dict, status_code=201)
async def create_charger(charger_data: ChargerCreate, admin_user: User = Depends(require_admin())):
    """Onboard a new charger"""
    
    # Verify station exists
    station = await ChargingStation.filter(id=charger_data.station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")
    
    # Validate + canonicalize connector types up front ("type 2" -> "Type2")
    # so an invalid type fails fast before any row is written.
    canonical_types = []
    for connector_input in charger_data.connectors:
        canonical_type = canonical_connector_type(connector_input.connector_type)
        if canonical_type is None:
            raise HTTPException(status_code=400, detail="Invalid connector type")
        canonical_types.append(canonical_type)

    # Generate unique charge point ID
    charge_point_id = str(uuid.uuid4())

    try:
        charger = await _create_charger_rows(
            charger_data, canonical_types, charge_point_id,
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

async def _upsert_charger_tariff(charger_id: int, gst_incl_value) -> None:
    """Create or update the single charger-specific tariff, race-safe.

    Preserves the existing GST rate if a tariff already exists, else the model
    default. A concurrent double-submit can have two requests both find no row
    and both attempt an insert; the UNIQUE(charger_id) constraint (migration 47)
    makes the loser raise IntegrityError, which we resolve as an update rather
    than a 500. See upsert-race-hardening issue 01.
    """
    existing = await Tariff.filter(charger_id=charger_id).first()
    if existing:
        gst = existing.gst_percent
    else:
        gst = Decimal(str(Tariff._meta.fields_map["gst_percent"].default))
    gst_incl = Decimal(str(gst_incl_value))
    rate = back_calc_base_rate(gst_incl, gst)
    defaults = {"rate_per_kwh": rate, "rate_gst_included": gst_incl, "gst_percent": gst}
    try:
        await Tariff.update_or_create(defaults=defaults, charger_id=charger_id)
    except IntegrityError:
        await Tariff.filter(charger_id=charger_id).update(**defaults)

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

    # Tariff is handled out-of-band — back-calc the base rate from the
    # operator-typed GST-inclusive value and persist both columns. ADR 0026.
    rate_gst_included = update_dict.pop("rate_gst_included", None)
    if rate_gst_included is not None:
        await _upsert_charger_tariff(charger_id, rate_gst_included)

    # Connector type lives on the connector row(s), not the charger. Validate and
    # apply to all of this charger's connectors so socket-vs-tethered gating is
    # correct. See socket-charger-classification issue 01.
    connector_type = update_dict.pop("connector_type", None)
    if connector_type is not None:
        canonical_type = canonical_connector_type(connector_type)
        if canonical_type is None:
            raise HTTPException(status_code=400, detail="Invalid connector type")
        await Connector.filter(charger_id=charger_id).update(
            connector_type=canonical_type
        )
        # Keep the in-memory socket-classification cache coherent. The hot-path
        # StatusNotification handler reads connector_type from
        # connected_charge_points (populated only at BootNotification), so
        # without this refresh socket-vs-tethered gating would keep using the
        # OLD type for a currently-connected charger until it reboots.
        from core.connection_manager import connection_manager
        cached = connection_manager.connected_charge_points.get(
            charger.charge_point_string_id
        )
        if cached is not None:
            cached["connector_type"] = canonical_type.value

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

    # Wallet gate (ADR 0011) applies only to wallet-funded customer sessions.
    # Internal-role (ADMIN/FRANCHISEE) sessions are operational and decoupled
    # from wallets (ADR 0004), so they are never gated.
    if not wallet_charging_enabled() and user.role not in INTERNAL_ROLES:
        raise HTTPException(status_code=403, detail="Wallet charging is temporarily disabled")

    # Use the user's RFID card ID as idTag for OCPP identification
    if not user.rfid_card_id:
        raise HTTPException(status_code=409, detail="User does not have an RFID card ID assigned")
    
    actual_id_tag = user.rfid_card_id
    logger.info(f"🚀 Remote start requested by user {user.clerk_user_id} (role: {user.role}) using idTag: {actual_id_tag}")
    
    # connector_id=1 covers all single-connector chargers currently in the fleet.
    # Multi-connector support (user selection of connector) is out of scope for v1.

    charger = await Charger.filter(id=charger_id).first()
    if charger and charger.purpose == ChargerPurposeEnum.TEST and user.role not in INTERNAL_ROLES:
        # Refuse BEFORE any money moves. StartTransaction blocks a TEST unit
        # too, but by then a QR customer has already paid and would need a
        # refund for a session that was never going to start. ADR 0028.
        raise HTTPException(status_code=403, detail="This charger is not available for public use")
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    
    # Check if charger status is suitable for remote start. Socket chargers may
    # not transition to Preparing (no CP signal) — the shared startable-statuses
    # helper widens the gate to Available for them (charger_type_service).
    from services.charger_type_service import startable_statuses_for_charger
    allowed_statuses = await startable_statuses_for_charger(charger.charge_point_string_id)
    if charger.latest_status not in allowed_statuses:
        expected = "Preparing or Available" if len(allowed_statuses) > 1 else "Preparing"
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
    outcome = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStartTransaction",
        {
            "connector_id": connector_id,
            "id_tag": actual_id_tag  # Use authenticated user's RFID card ID
        }
    )

    # The charger answered and declined — busy, connector occupied, id_tag not
    # authorised. Deliberately not a 5xx: the system worked and the answer was
    # no. Reporting this as success left the operator waiting for a session
    # that was never going to start.
    if outcome.is_refused:
        logger.warning(
            f"Charger refused start for {charger.charge_point_string_id} "
            f"connector {connector_id} (status={outcome.status})"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Charger declined the start command. It may be busy or the "
                "connector unavailable — please try again."
            ),
        )

    # A charger that doesn't ACK in time is offline/slow — an upstream gateway
    # condition, not a server fault. 504 is excluded from Sentry's
    # failed-request reporting (see monitoring_service), unlike a 500 which
    # would spam error tracking with expected operational noise.
    if outcome.is_unanswered:
        raise HTTPException(
            status_code=504,
            detail="Charger did not respond in time. It may be offline — please try again.",
        )

    return {
        "success": True,
        "message": "Remote start accepted by charger",
        "connector_id": connector_id
    }

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
    outcome = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStopTransaction",
        {"transaction_id": transaction.id}
    )

    # A refused stop is the dangerous case: the session is still live and still
    # billing, so the operator must not be told it ended. Deliberately not a 5xx
    # — the charger answered and declined, which is the system working.
    if outcome.is_refused:
        logger.warning(
            f"Charger refused stop for transaction {transaction.id} "
            f"(status={outcome.status})"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Charger declined the stop command. The session is still running. "
                "Try again, and use force-stop if it keeps refusing."
            ),
        )

    if outcome.is_unanswered:
        # Never delivered, or no reply in time — an upstream condition rather
        # than a server fault, so 504 rather than a 500 that would spam Sentry.
        logger.warning(
            f"Remote stop unanswered for transaction {transaction.id}: {outcome.response}"
        )
        raise HTTPException(
            status_code=504,
            detail=(
                "Charger did not respond, so the session may still be running. "
                "It may be offline — please try again."
            ),
        )

    action_type = "Admin override stop" if is_admin and not is_owner else "Remote stop"
    return {
        "success": True,
        "message": f"{action_type} accepted by charger",
        "transaction_id": transaction.id,
        "charger_id": charger_id,
        "transaction_owner": transaction.user_id,
        "stopped_by": user.id
    }

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
    outcome = await send_ocpp_request(
        charger.charge_point_string_id,
        "ChangeAvailability",
        {
            "connector_id": connector_id,
            "type": type
        }
    )

    if outcome.answered:
        # Behaviour here is deliberately unchanged (ADR 0008): `Scheduled` is an
        # acceptance — the charger will apply it when the current transaction
        # ends — and only `Accepted`/`Scheduled` persist admin intent. The
        # explicit tuple is kept rather than `outcome.is_accepted` so this stays
        # visibly tied to ADR 0008 rather than to a shared status set that could
        # later drift.
        ocpp_status = outcome.status or str(outcome.response)

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
        # Unanswered, not refused — a refusal takes the branch above and is
        # recorded with its OCPP status. 504 rather than 500: an offline or slow
        # charger is an upstream condition, not a server fault.
        raise HTTPException(
            status_code=504,
            detail=f"Charger did not respond to the availability command: {outcome.response}",
        )

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
    outcome = await send_ocpp_request(
        charger.charge_point_string_id,
        "Reset",
        {"type": type}
    )

    # A charger that answers "Rejected" has not rebooted. Reading the reply
    # itself as success wrote a `charger.reset` audit event for a reboot that
    # never happened — a durable false record, worse than the misleading
    # message, because someone reads it back months later and reasons from it.
    if outcome.is_refused:
        logger.warning(
            f"Charger {charger.charge_point_string_id} refused {type} reset "
            f"(status={outcome.status})"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Charger declined the {type} reset. It may be mid-transaction "
                "or otherwise unable to reboot right now."
            ),
        )

    if outcome.is_unanswered:
        raise HTTPException(
            status_code=504,
            detail=f"Charger did not respond to the reset command: {outcome.response}",
        )

    # Refusal and silence both raised above, so this is an acceptance.
    await log_audit_event(
        action="charger.reset",
        entity_type="charger",
        entity_id=charger.charge_point_string_id,
        actor_type="admin",
        actor=admin_user,
        changes={"reset_type": type, "ocpp_response": outcome.status},
    )

    return {
        "success": True,
        "message": f"{type} reset accepted by the charger",
        "reset_type": type,
        "charger_id": charger_id
    }

@router.get("/{charger_id}/logs", response_model=LogsListResponse)
async def get_charger_logs(
    charger_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    direction: Optional[str] = Query(None, regex="^(IN|OUT)$"),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    admin_user: User = Depends(require_admin()),
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

# ============ Charger Auth Key provisioning (ADR 0020 / ADR 0029) ============

class AuthKeyResponse(BaseModel):
    charge_point_string_id: str
    auth_key: str
    rotated: bool
    warning: str


class RotateAuthKeyRequest(BaseModel):
    # The charger's own name, echoed back by the caller. A bare `confirm: true`
    # would be satisfied by muscle memory or a copy-pasted curl; echoing an
    # identifier you had to look up is the cheapest thing that demonstrates you
    # know *which* unit you are about to cut off.
    confirm_charger_name: str


def _rotation_confirmation_value(charger) -> str:
    """What the caller must echo to rotate. Falls back to the string id so an
    unnamed charger cannot skip the check entirely."""
    return (charger.name or "").strip() or charger.charge_point_string_id


async def _mint_and_store_key(charger, admin_user, *, rotated: bool) -> AuthKeyResponse:
    """Shared tail of provisioning and rotation: mint, store the hash, audit."""
    plaintext = charger_auth_service.generate_auth_key()
    charger.auth_key_hash = charger_auth_service.hash_auth_key(plaintext)
    await charger.save(update_fields=["auth_key_hash", "updated_at"])

    # Two explicit calls rather than a ternary on `action=`: the audit-registry
    # drift guard (tests/test_audit_actions.py) scans for the literal that
    # follows `action=`, so a ternary would hide one action from it.
    if rotated:
        await log_audit_event(
            action="charger.auth_rotated",
            entity_type="charger",
            entity_id=charger.charge_point_string_id,
            actor_type="admin",
            actor=admin_user,
        )
    else:
        await log_audit_event(
            action="charger.auth_provisioned",
            entity_type="charger",
            entity_id=charger.charge_point_string_id,
            actor_type="admin",
            actor=admin_user,
        )
    # Deliberately logs the outcome and the charger, never the key.
    logger.info(
        "🔑 Charger Auth Key %s for %s by admin %s",
        "rotated" if rotated else "provisioned", charger.charge_point_string_id, admin_user.id,
    )

    return AuthKeyResponse(
        charge_point_string_id=charger.charge_point_string_id,
        auth_key=plaintext,
        rotated=rotated,
        warning="Copy this key now — it is shown once and cannot be retrieved again.",
    )


@router.post("/{charger_id}/auth-key", response_model=AuthKeyResponse)
async def provision_charger_auth_key(
    charger_id: int,
    admin_user: User = Depends(require_admin()),
):
    """Mint a charger's **first** Charger Auth Key, revealing it once.

    Deliberately incapable of destroying an existing key: a charger that already
    has one is refused with 409 and must go through the explicit rotate
    endpoint. Provisioning and rotation used to be the same call, with which one
    you got decided by server state the caller could not see — so an admin with
    no way of knowing a key existed could destroy a working credential in one
    click, and only learn which operation had happened from the response.

    The plaintext is returned here and never again; only its SHA-256 is stored.
    """
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    if charger.auth_key_hash:
        raise HTTPException(
            status_code=409,
            detail=(
                "This charger already has an auth key. Rotating it will cut the "
                "charger off until the new key is loaded onto the unit — use the "
                "rotate endpoint to do that deliberately."
            ),
        )

    return await _mint_and_store_key(charger, admin_user, rotated=False)


@router.post("/{charger_id}/auth-key/rotate", response_model=AuthKeyResponse)
async def rotate_charger_auth_key(
    charger_id: int,
    body: RotateAuthKeyRequest,
    admin_user: User = Depends(require_admin()),
):
    """Replace a charger's **Charger Auth Key**, revealing the new one once.

    Destructive and irreversible. Rotation has **no grace overlap**: the old
    hash is replaced immediately, so the charger fails authentication from that
    instant until the new key is loaded onto it by charger-side tooling. The
    fleet sits behind carrier NAT with no inbound path, so recovery from an
    unintended rotation means physically visiting the unit.

    The caller must echo the charger's own name to proceed. That converts a slip
    into a deliberate act; it cannot stop a confident mistake, which would need
    two-person approval and is disproportionate while this key gates Diagnostic
    Bundle upload only (ADR 0020 remains PROPOSED, so the OCPP WebSocket
    handshake does not consult it yet).
    """
    charger = await Charger.get_or_none(id=charger_id)
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    if not charger.auth_key_hash:
        raise HTTPException(
            status_code=409,
            detail="This charger has no auth key to rotate — provision one instead.",
        )

    expected = _rotation_confirmation_value(charger)
    if body.confirm_charger_name.strip().casefold() != expected.casefold():
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation does not match. Type '{expected}' to rotate this charger's key.",
        )

    return await _mint_and_store_key(charger, admin_user, rotated=True)
