"""Franchisee portal API.

All endpoints are scoped to the authenticated franchisee's stations.
Uses require_franchisee() which returns (User, Franchisee).
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from tortoise.expressions import Q

from models import (
    Franchisee,
    FranchiseeStatusEnum,
    ChargingStation,
    Charger,
    Transaction,
    MeterValue,
    CommissionLedgerEntry,
    TransactionStatusEnum,
    ChargerQRCode,
    QRPayment,
)
from auth_middleware import require_franchisee
from crud import log_audit_event
from services.razorpay_service import (
    razorpay_service, build_qr_payee_name, build_qr_description,
)

logger = logging.getLogger("ocpp-server")

router = APIRouter(
    prefix="/api/franchisee",
    tags=["Franchisee Portal"],
)


# ─── Helpers ─────────────────────────────────────────────────────────

async def _get_franchisee_station_ids(franchisee_id: int) -> list[int]:
    stations = await ChargingStation.filter(
        franchisee_id=franchisee_id
    ).values_list("id", flat=True)
    return list(stations)


async def _get_franchisee_charger_ids(franchisee_id: int) -> list[int]:
    station_ids = await _get_franchisee_station_ids(franchisee_id)
    if not station_ids:
        return []
    chargers = await Charger.filter(
        station_id__in=station_ids
    ).values_list("id", flat=True)
    return list(chargers)


async def _verify_charger_ownership(
    charger_id: int, franchisee_id: int
) -> Charger:
    """Return charger if owned by franchisee, else 403."""
    charger = await Charger.filter(id=charger_id).select_related("station").first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    if not charger.station.franchisee_id or charger.station.franchisee_id != franchisee_id:
        raise HTTPException(status_code=403, detail="Not your charger")
    return charger


# ─── Dashboard ───────────────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(auth=Depends(require_franchisee())):
    user, franchisee = auth

    station_ids = await _get_franchisee_station_ids(franchisee.id)
    charger_ids = await _get_franchisee_charger_ids(franchisee.id)

    active_sessions = 0
    if charger_ids:
        active_sessions = await Transaction.filter(
            charger_id__in=charger_ids,
            transaction_status__in=[
                TransactionStatusEnum.RUNNING,
                TransactionStatusEnum.STARTED,
                TransactionStatusEnum.PENDING_START,
            ],
        ).count()

    total_settlements = await CommissionLedgerEntry.filter(
        franchisee_id=franchisee.id
    ).count()

    from tortoise.functions import Sum
    payout_agg = await CommissionLedgerEntry.filter(
        franchisee_id=franchisee.id
    ).annotate(total=Sum("franchisee_payout")).values("total")
    total_payout = payout_agg[0]["total"] if payout_agg and payout_agg[0]["total"] else 0

    return {
        "station_count": len(station_ids),
        "charger_count": len(charger_ids),
        "active_sessions": active_sessions,
        "total_settlements": total_settlements,
        "total_payout": str(total_payout),
        "franchisee_status": franchisee.status.value if hasattr(franchisee.status, "value") else str(franchisee.status),
    }


# ─── Stations ────────────────────────────────────────────────────────

@router.get("/stations")
async def list_stations(auth=Depends(require_franchisee())):
    _, franchisee = auth

    stations = await ChargingStation.filter(
        franchisee_id=franchisee.id
    ).prefetch_related("chargers")

    return [
        {
            "id": s.id,
            "name": s.name,
            "address": s.address,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "state": s.state,
            "state_code": s.state_code,
            "pincode": s.pincode,
            "charger_count": len(s.chargers),
        }
        for s in stations
    ]


@router.get("/stations/{station_id}")
async def get_station(station_id: int, auth=Depends(require_franchisee())):
    _, franchisee = auth

    station = await ChargingStation.filter(
        id=station_id, franchisee_id=franchisee.id
    ).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    chargers = await Charger.filter(station_id=station_id)

    return {
        "station": {
            "id": station.id,
            "name": station.name,
            "address": station.address,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "state": station.state,
            "state_code": station.state_code,
            "pincode": station.pincode,
        },
        "chargers": [
            {
                "id": c.id,
                "charge_point_string_id": c.charge_point_string_id,
                "name": c.name,
                "model": c.model,
                "vendor": c.vendor,
                "latest_status": c.latest_status,
                "last_heart_beat_time": c.last_heart_beat_time.isoformat() if c.last_heart_beat_time else None,
            }
            for c in chargers
        ],
    }


# ─── Chargers ────────────────────────────────────────────────────────

@router.get("/chargers/{charger_id}")
async def get_charger(charger_id: int, auth=Depends(require_franchisee())):
    _, franchisee = auth
    charger = await _verify_charger_ownership(charger_id, franchisee.id)

    return {
        "id": charger.id,
        "charge_point_string_id": charger.charge_point_string_id,
        "name": charger.name,
        "model": charger.model,
        "vendor": charger.vendor,
        "serial_number": charger.serial_number,
        "firmware_version": charger.firmware_version,
        "latest_status": charger.latest_status,
        "last_heart_beat_time": charger.last_heart_beat_time.isoformat() if charger.last_heart_beat_time else None,
        "station_id": charger.station_id,
        "station_name": charger.station.name,
    }


@router.post("/chargers/{charger_id}/remote-stop")
async def remote_stop(charger_id: int, auth=Depends(require_franchisee())):
    """Stop charging on own charger."""
    _, franchisee = auth
    charger = await _verify_charger_ownership(charger_id, franchisee.id)

    active_txn = await Transaction.filter(
        charger_id=charger_id,
        transaction_status__in=["STARTED", "PENDING_START", "RUNNING"],
    ).first()
    if not active_txn:
        raise HTTPException(status_code=409, detail="No active session")

    from main import send_ocpp_request
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "RemoteStopTransaction",
        {"transaction_id": active_txn.id},
    )
    if success:
        return {"success": True, "message": "Stop command sent"}
    raise HTTPException(status_code=500, detail=f"Stop failed: {response}")


@router.post("/chargers/{charger_id}/reset")
async def reset_charger(charger_id: int, auth=Depends(require_franchisee())):
    """Soft reset own charger."""
    _, franchisee = auth
    charger = await _verify_charger_ownership(charger_id, franchisee.id)

    from main import send_ocpp_request
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "Reset",
        {"type": "Soft"},
    )
    if success:
        return {"success": True, "message": "Soft reset sent"}
    raise HTTPException(status_code=500, detail=f"Reset failed: {response}")


@router.post("/chargers/{charger_id}/change-availability")
async def change_availability(
    charger_id: int,
    available: bool = Query(...),
    auth=Depends(require_franchisee()),
):
    """Change charger availability — franchisee-facing surface.

    Takes a boolean (`?available=true|false`) for operator-intuitive UX.
    Internally fixed to `connector_id=0` (whole-charger) and maps the boolean
    to OCPP Operative/Inoperative.

    The parallel admin endpoint at `routers/chargers.change_charger_availability`
    instead takes OCPP-aligned vocabulary (`?type=Operative|Inoperative&connector_id=0`)
    so admins debugging at the OCPP layer have explicit terminology. This
    divergence is intentional; see docs/v1/comprehensive-architecture-documentation.md
    "Charger control surface" for the rationale. Do not unify them blindly.
    """
    _, franchisee = auth
    charger = await _verify_charger_ownership(charger_id, franchisee.id)

    from main import send_ocpp_request
    success, response = await send_ocpp_request(
        charger.charge_point_string_id,
        "ChangeAvailability",
        {
            "connector_id": 0,
            "type": "Operative" if available else "Inoperative",
        },
    )
    if success:
        return {"success": True, "message": "Availability changed"}
    raise HTTPException(status_code=500, detail=f"Failed: {response}")


# ─── Transactions ────────────────────────────────────────────────────

@router.get("/transactions")
async def list_transactions(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    auth=Depends(require_franchisee()),
):
    _, franchisee = auth
    charger_ids = await _get_franchisee_charger_ids(franchisee.id)

    if not charger_ids:
        return {"data": [], "total": 0, "page": page, "limit": limit}

    query = Transaction.filter(charger_id__in=charger_ids)
    if status:
        query = query.filter(transaction_status=status)

    total = await query.count()
    txns = await query.offset((page - 1) * limit).limit(limit).order_by(
        "-created_at"
    ).prefetch_related("charger")

    return {
        "data": [
            {
                "id": t.id,
                "charger_id": t.charger_id,
                "charger_name": t.charger.name if t.charger else None,
                "energy_consumed_kwh": t.energy_consumed_kwh,
                "energy_charge": str(t.energy_charge) if t.energy_charge else None,
                "gst_amount": str(t.gst_amount) if t.gst_amount else None,
                "total_billed": str(t.total_billed) if t.total_billed else None,
                "transaction_status": t.transaction_status,
                "start_time": t.start_time.isoformat() if t.start_time else None,
                "end_time": t.end_time.isoformat() if t.end_time else None,
            }
            for t in txns
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: int, auth=Depends(require_franchisee())
):
    _, franchisee = auth
    charger_ids = await _get_franchisee_charger_ids(franchisee.id)

    txn = await Transaction.filter(
        id=transaction_id, charger_id__in=charger_ids
    ).prefetch_related("charger").first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    meter_values = await MeterValue.filter(
        transaction_id=transaction_id
    ).order_by("created_at")

    return {
        "transaction": {
            "id": txn.id,
            "charger_id": txn.charger_id,
            "charger_name": txn.charger.name if txn.charger else None,
            "energy_consumed_kwh": txn.energy_consumed_kwh,
            "start_meter_kwh": txn.start_meter_kwh,
            "end_meter_kwh": txn.end_meter_kwh,
            "energy_charge": str(txn.energy_charge) if txn.energy_charge else None,
            "gst_amount": str(txn.gst_amount) if txn.gst_amount else None,
            "total_billed": str(txn.total_billed) if txn.total_billed else None,
            "transaction_status": txn.transaction_status,
            "start_time": txn.start_time.isoformat() if txn.start_time else None,
            "end_time": txn.end_time.isoformat() if txn.end_time else None,
            "stop_reason": txn.stop_reason,
        },
        "meter_values": [
            {
                "reading_kwh": mv.reading_kwh,
                "current": mv.current,
                "voltage": mv.voltage,
                "power_kw": mv.power_kw,
                "created_at": mv.created_at.isoformat(),
            }
            for mv in meter_values
        ],
    }


# ─── Settlements ─────────────────────────────────────────────────────

@router.get("/settlements")
async def list_settlements(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    auth=Depends(require_franchisee()),
):
    _, franchisee = auth

    query = CommissionLedgerEntry.filter(franchisee_id=franchisee.id)
    total = await query.count()
    entries = await query.offset((page - 1) * limit).limit(limit).order_by(
        "-created_at"
    )

    return {
        "data": [
            {
                "id": e.id,
                "transaction_id": e.transaction_id,
                "payment_method": e.payment_method,
                "gross_amount": str(e.gross_amount),
                "franchisee_payout": str(e.franchisee_payout),
                "commission_percent": str(e.commission_percent),
                "platform_commission": str(e.platform_commission),
                "tds_amount": str(e.tds_amount),
                "energy_consumed_kwh": e.energy_consumed_kwh,
                "settlement_status": e.settlement_status.value if hasattr(e.settlement_status, "value") else str(e.settlement_status),
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


# ─── Profile & KYC ──────────────────────────────────────────────────

@router.get("/profile")
async def get_profile(auth=Depends(require_franchisee())):
    _, franchisee = auth

    station_count = await ChargingStation.filter(
        franchisee_id=franchisee.id
    ).count()

    return {
        "id": franchisee.id,
        "business_name": franchisee.business_name,
        "business_type": franchisee.business_type.value if franchisee.business_type else None,
        "contact_name": franchisee.contact_name,
        "contact_email": franchisee.contact_email,
        "contact_phone": franchisee.contact_phone,
        "address": franchisee.address,
        "pan_number": franchisee.pan_number,
        "gstin": franchisee.gstin,
        "state": franchisee.state,
        "state_code": franchisee.state_code,
        "commission_percent": str(franchisee.commission_percent),
        "tds_rate_percent": str(franchisee.tds_rate_percent),
        "status": franchisee.status.value if hasattr(franchisee.status, "value") else str(franchisee.status),
        "status_reason": franchisee.status_reason,
        "razorpay_account_id": franchisee.razorpay_account_id,
        "razorpay_account_status": franchisee.razorpay_account_status,
        "razorpay_onboarding_url": franchisee.razorpay_onboarding_url,
        "kyc_submitted_at": franchisee.kyc_submitted_at.isoformat() if franchisee.kyc_submitted_at else None,
        "kyc_verified_at": franchisee.kyc_verified_at.isoformat() if franchisee.kyc_verified_at else None,
        "station_count": station_count,
        "created_at": franchisee.created_at.isoformat(),
    }


# ─── QR Codes ────────────────────────────────────────────────────────


class CreatePortalQRCodeRequest(BaseModel):
    charger_id: int


def _franchisee_can_own_qrs(franchisee: Franchisee) -> bool:
    """Deprecated — all QRs are platform-owned. Retained so legacy
    response fields (``can_create_direct``) keep a stable shape for the
    frontend. Always False now that QRs no longer scope to the
    franchisee's linked account; the platform transfers the franchisee's
    share post-settlement via Route instead."""
    return False


def _qr_owner_kind(account_id: Optional[str]) -> str:
    return "franchisee" if account_id else "platform"


async def _serialize_franchisee_qr(
    qr: ChargerQRCode, franchisee: Franchisee
) -> dict:
    business = franchisee.business_name
    charger_name = qr.charger.name or qr.charger.charge_point_string_id if qr.charger else ""
    return {
        "id": qr.id,
        "charger_id": qr.charger_id,
        "charger_name": qr.charger.name if qr.charger else None,
        "razorpay_qr_code_id": qr.razorpay_qr_code_id,
        "image_url": qr.image_url,
        "short_url": qr.short_url,
        "is_active": qr.is_active,
        "owner": _qr_owner_kind(qr.owner_razorpay_account_id),
        "payee_display_name": build_qr_payee_name(business, charger_name),
        "created_at": qr.created_at.isoformat(),
    }


async def _ensure_charger_belongs_to_franchisee(
    charger_id: int, franchisee_id: int
) -> Charger:
    """Load a charger and 403 if it doesn't belong to the franchisee's
    stations. Used by every mutating portal endpoint."""
    owned_ids = await _get_franchisee_charger_ids(franchisee_id)
    if charger_id not in owned_ids:
        raise HTTPException(
            status_code=403,
            detail="Charger does not belong to your stations.",
        )
    charger = await Charger.filter(id=charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")
    return charger


async def _create_franchisee_qr(
    charger: Charger, franchisee: Franchisee
) -> ChargerQRCode:
    """Create a platform-owned QR for one of this franchisee's chargers.

    The QR is never scoped to the franchisee's linked account — all
    payments flow to the platform first, and the franchisee's share is
    disbursed via a Route transfer after the session settles.
    """
    business_name = franchisee.business_name
    charger_name = charger.name or charger.charge_point_string_id

    result = razorpay_service.create_qr_code(
        payee_name=build_qr_payee_name(business_name, charger_name),
        description=build_qr_description(business_name, charger_name),
        account_id=None,
    )
    qr = await ChargerQRCode.create(
        charger=charger,
        razorpay_qr_code_id=result["id"],
        image_url=result.get("image_url", ""),
        short_url=result.get("short_url"),
        is_active=True,
        owner_razorpay_account_id=None,
    )
    await qr.fetch_related("charger")
    return qr


@router.get("/qr-codes")
async def list_qr_codes(auth=Depends(require_franchisee())):
    _, franchisee = auth
    charger_ids = await _get_franchisee_charger_ids(franchisee.id)

    base = {
        "can_create_direct": _franchisee_can_own_qrs(franchisee),
        "razorpay_account_status": franchisee.razorpay_account_status,
        "franchisee_status": (
            franchisee.status.value if hasattr(franchisee.status, "value")
            else str(franchisee.status)
        ),
    }

    if not charger_ids:
        return {"data": [], **base}

    qr_codes = await ChargerQRCode.filter(
        charger_id__in=charger_ids
    ).prefetch_related("charger").order_by("-is_active", "-created_at")

    return {
        "data": [
            await _serialize_franchisee_qr(qr, franchisee) for qr in qr_codes
        ],
        **base,
    }


@router.post("/qr-codes")
async def create_portal_qr_code(
    body: CreatePortalQRCodeRequest,
    auth=Depends(require_franchisee()),
):
    """Create a QR code for one of this franchisee's chargers.

    Scopes the QR to the franchisee's Razorpay linked account when the
    account is ACTIVE (so the rendered QR image displays their business
    name). Until then, falls back to a platform-owned QR that can be
    upgraded via /regenerate after onboarding completes.
    """
    user, franchisee = auth

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured")

    charger = await _ensure_charger_belongs_to_franchisee(
        body.charger_id, franchisee.id
    )

    existing = await ChargerQRCode.filter(charger=charger, is_active=True).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Active QR code already exists for this charger. Regenerate instead if you want to refresh it.",
        )

    try:
        qr = await _create_franchisee_qr(charger, franchisee)
    except Exception as e:
        logger.exception("Franchisee %s QR create failed", franchisee.id)
        raise HTTPException(status_code=502, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="franchisee",
        actor=user,
        action="franchisee.qr_code_created",
        entity_type="charger_qr_code",
        entity_id=str(qr.id),
        changes={
            "charger_id": charger.id,
            "owner": _qr_owner_kind(qr.owner_razorpay_account_id),
        },
    )
    return await _serialize_franchisee_qr(qr, franchisee)


@router.post("/qr-codes/{qr_id}/regenerate")
async def regenerate_portal_qr_code(
    qr_id: int,
    auth=Depends(require_franchisee()),
):
    """Close the existing QR and create a new one.

    Used after Razorpay KYC completes to upgrade a platform-owned QR
    into a franchisee-owned one (the big label on the QR image flips
    from VoltLync to the franchisee's business name).
    """
    user, franchisee = auth

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured")

    qr = await ChargerQRCode.filter(id=qr_id).prefetch_related("charger").first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")
    await _ensure_charger_belongs_to_franchisee(qr.charger_id, franchisee.id)

    if qr.is_active:
        try:
            razorpay_service.close_qr_code(
                qr.razorpay_qr_code_id,
                account_id=qr.owner_razorpay_account_id,
            )
        except Exception as e:
            logger.warning("Razorpay close failed during regenerate (continuing): %s", e)
        qr.is_active = False
        await qr.save()

    try:
        new_qr = await _create_franchisee_qr(qr.charger, franchisee)
    except Exception as e:
        logger.exception("Franchisee %s QR regenerate failed", franchisee.id)
        raise HTTPException(status_code=502, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="franchisee",
        actor=user,
        action="franchisee.qr_code_regenerated",
        entity_type="charger_qr_code",
        entity_id=str(new_qr.id),
        changes={
            "previous_qr_id": qr.id,
            "charger_id": qr.charger_id,
            "owner": _qr_owner_kind(new_qr.owner_razorpay_account_id),
        },
    )
    return await _serialize_franchisee_qr(new_qr, franchisee)


@router.post("/qr-codes/{qr_id}/close")
async def close_portal_qr_code(
    qr_id: int,
    auth=Depends(require_franchisee()),
):
    """Close (deactivate) a QR code the franchisee owns."""
    user, franchisee = auth

    qr = await ChargerQRCode.filter(id=qr_id).first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")
    await _ensure_charger_belongs_to_franchisee(qr.charger_id, franchisee.id)

    if not qr.is_active:
        raise HTTPException(status_code=400, detail="QR code already inactive")

    try:
        razorpay_service.close_qr_code(
            qr.razorpay_qr_code_id,
            account_id=qr.owner_razorpay_account_id,
        )
    except Exception as e:
        logger.warning("Razorpay close failed (marking inactive anyway): %s", e)

    qr.is_active = False
    await qr.save()

    await log_audit_event(
        actor_type="franchisee",
        actor=user,
        action="franchisee.qr_code_closed",
        entity_type="charger_qr_code",
        entity_id=str(qr.id),
        changes={"charger_id": qr.charger_id},
    )
    return {"message": "QR code closed", "id": qr.id}
