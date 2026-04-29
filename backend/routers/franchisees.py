# routers/franchisees.py
import logging
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, EmailStr
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction

from models import (
    Franchisee, FranchiseeStatusEnum, FranchiseeBusinessTypeEnum,
    FranchiseeStakeholder,
    CommissionAuditLog, CommissionChangeReasonEnum, CommissionLedgerEntry,
    SettlementStatusEnum,
    ChargingStation, User, UserRoleEnum,
)
from auth_middleware import require_admin
from crud import log_audit_event
from services import clerk_invitation_service

logger = logging.getLogger("ocpp-server")

# ─── Pydantic Schemas ───────────────────────────────────────────────

class FranchiseeCreate(BaseModel):
    business_name: str
    contact_name: str
    contact_email: str
    contact_phone: str
    commission_percent: Decimal = Decimal("20.00")
    tds_rate_percent: Decimal = Decimal("10.00")
    notes: Optional[str] = None


class FranchiseeUpdate(BaseModel):
    business_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    address: Optional[str] = None
    business_type: Optional[FranchiseeBusinessTypeEnum] = None
    pan_number: Optional[str] = None
    gstin: Optional[str] = None
    tan_number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    bank_account_type: Optional[str] = None  # 'savings' | 'current'
    notes: Optional[str] = None


class CommissionUpdate(BaseModel):
    new_percent: Decimal
    reason: CommissionChangeReasonEnum
    effective_from: date
    notes: Optional[str] = None


class TDSUpdate(BaseModel):
    tds_rate_percent: Decimal
    notes: Optional[str] = None


class StationAssign(BaseModel):
    station_ids: List[int]


class FranchiseeResponse(BaseModel):
    id: int
    business_name: str
    business_type: Optional[str] = None
    contact_name: str
    contact_email: str
    contact_phone: str
    address: Optional[str] = None
    pan_number: Optional[str] = None
    gstin: Optional[str] = None
    tan_number: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    bank_account_type: Optional[str] = None
    commission_percent: Decimal
    tds_rate_percent: Decimal
    status: str
    status_reason: Optional[str] = None
    razorpay_account_id: Optional[str] = None
    razorpay_account_status: Optional[str] = None
    razorpay_product_id: Optional[str] = None
    razorpay_onboarding_url: Optional[str] = None
    kyc_verifications: Optional[dict] = None
    bank_account_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    station_count: int = 0
    activated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    notes: Optional[str] = None
    # Populated only on create / resend responses. None on list/detail reads —
    # invitation state isn't persisted server-side, we rely on Clerk's own
    # invitation dashboard as the source of truth.
    invitation_sent: Optional[bool] = None

    class Config:
        from_attributes = True


class FranchiseeListResponse(BaseModel):
    data: List[FranchiseeResponse]
    total: int
    page: int
    limit: int


class CommissionAuditResponse(BaseModel):
    id: int
    previous_percent: Optional[Decimal] = None
    new_percent: Decimal
    reason: str
    effective_from: date
    notes: Optional[str] = None
    changed_by_email: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Helpers ─────────────────────────────────────────────────────────

async def _franchisee_to_response(f: Franchisee) -> dict:
    station_count = await ChargingStation.filter(franchisee_id=f.id).count()
    return {
        "id": f.id,
        "business_name": f.business_name,
        "business_type": f.business_type.value if f.business_type else None,
        "contact_name": f.contact_name,
        "contact_email": f.contact_email,
        "contact_phone": f.contact_phone,
        "address": f.address,
        "pan_number": f.pan_number,
        "gstin": f.gstin,
        "tan_number": f.tan_number,
        "city": f.city,
        "state": f.state,
        "state_code": f.state_code,
        "pincode": f.pincode,
        "commission_percent": f.commission_percent,
        "tds_rate_percent": f.tds_rate_percent,
        "status": f.status.value if hasattr(f.status, "value") else str(f.status),
        "status_reason": f.status_reason,
        "razorpay_account_id": f.razorpay_account_id,
        "razorpay_account_status": f.razorpay_account_status,
        "razorpay_product_id": f.razorpay_product_id,
        "razorpay_onboarding_url": f.razorpay_onboarding_url,
        "kyc_verifications": f.kyc_verifications,
        "bank_account_name": f.bank_account_name,
        "bank_account_number": f.bank_account_number,
        "bank_ifsc_code": f.bank_ifsc_code,
        "bank_account_type": f.bank_account_type,
        "station_count": station_count,
        "activated_at": f.activated_at,
        "created_at": f.created_at,
        "updated_at": f.updated_at,
        "notes": f.notes,
    }


# ─── Router ──────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/api/admin/franchisees",
    tags=["Franchisee Management"],
)


@router.post("", response_model=FranchiseeResponse)
async def create_franchisee(
    body: FranchiseeCreate,
    admin: User = Depends(require_admin()),
):
    """Create a franchisee with minimal info. Also creates a FRANCHISEE user.

    User and Franchisee rows are created inside a single transaction so a
    failure on either side leaves the DB clean — no orphan User rows if the
    Franchisee insert fails, and no orphan Franchisee rows if anything after
    the User insert fails.
    """
    try:
        async with in_transaction():
            user = await User.create(
                email=body.contact_email,
                full_name=body.contact_name,
                role=UserRoleEnum.FRANCHISEE,
                is_active=True,
            )
            franchisee = await Franchisee.create(
                business_name=body.business_name,
                contact_name=body.contact_name,
                contact_email=body.contact_email,
                contact_phone=body.contact_phone,
                commission_percent=body.commission_percent,
                tds_rate_percent=body.tds_rate_percent,
                notes=body.notes,
                onboarded_by=admin,
                user=user,
            )
    except IntegrityError as e:
        # Tortoise wraps the asyncpg error via `IntegrityError(exc)` without
        # `raise ... from ...`, so the original sits on __context__ (implicit
        # chaining) and in args[0], not __cause__. Only a true unique
        # violation is a 409 — NOT NULL / CHECK / FK failures are
        # server-side bugs and should surface as 500 with real logs.
        original = e.__context__ if e.__context__ else (e.args[0] if e.args else None)
        if isinstance(original, asyncpg.exceptions.UniqueViolationError):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot create franchisee: email {body.contact_email} "
                    "or another unique field (PAN, GSTIN) is already in use."
                ),
            )
        logger.exception("Franchisee create failed with integrity error")
        raise HTTPException(
            status_code=500,
            detail="Could not create franchisee due to a database integrity error.",
        )

    # Commission audit log for initial setup
    await CommissionAuditLog.create(
        franchisee=franchisee,
        previous_percent=None,
        new_percent=body.commission_percent,
        reason=CommissionChangeReasonEnum.INITIAL_SETUP,
        effective_from=date.today(),
        changed_by=admin,
        notes="Initial franchisee creation",
    )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.created",
        entity_type="franchisee",
        entity_id=str(franchisee.id),
        changes={"business_name": body.business_name, "email": body.contact_email},
    )

    # Fire a Clerk invitation seeded with role=FRANCHISEE. Non-fatal:
    # Clerk/network failures must not roll back the franchisee record —
    # admin can retry via the resend endpoint.
    invitation_sent = False
    try:
        await clerk_invitation_service.send_invitation(
            email=body.contact_email,
            role=UserRoleEnum.FRANCHISEE.value,
            redirect_path="/franchisee",
        )
        invitation_sent = True
    except Exception:
        logger.exception(
            "Clerk invitation failed on franchisee create id=%s — admin can resend.",
            franchisee.id,
        )

    logger.info(
        "Franchisee created: id=%s name=%s invitation_sent=%s",
        franchisee.id, body.business_name, invitation_sent,
    )
    response = await _franchisee_to_response(franchisee)
    response["invitation_sent"] = invitation_sent
    return response


@router.post("/{franchisee_id}/resend-invitation")
async def resend_invitation(
    franchisee_id: int,
    admin: User = Depends(require_admin()),
):
    """Resend the Clerk invitation for a franchisee.

    Revokes any pending invitation for that email first so the link in
    the new email is the authoritative one. Safe to call repeatedly.
    """
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    try:
        await clerk_invitation_service.revoke_pending_invitation(
            franchisee.contact_email
        )
        await clerk_invitation_service.send_invitation(
            email=franchisee.contact_email,
            role=UserRoleEnum.FRANCHISEE.value,
            redirect_path="/franchisee",
        )
    except Exception:
        logger.exception(
            "Resend invitation failed for franchisee id=%s", franchisee_id
        )
        raise HTTPException(
            status_code=502,
            detail="Could not send invitation — check Clerk credentials and retry.",
        )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.invitation_resent",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"email": franchisee.contact_email},
    )

    return {"message": "Invitation sent", "email": franchisee.contact_email}


@router.get("", response_model=FranchiseeListResponse)
async def list_franchisees(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    _admin: User = Depends(require_admin()),
):
    """List franchisees with pagination, filtering, and search."""
    query = Franchisee.all()

    if status:
        query = query.filter(status=status)
    if search:
        query = query.filter(
            Q(business_name__icontains=search)
            | Q(contact_name__icontains=search)
            | Q(contact_email__icontains=search)
        )

    total = await query.count()
    franchisees = await query.offset((page - 1) * limit).limit(limit).order_by("-created_at")
    data = [await _franchisee_to_response(f) for f in franchisees]

    return {"data": data, "total": total, "page": page, "limit": limit}


@router.get("/{franchisee_id}", response_model=FranchiseeResponse)
async def get_franchisee(
    franchisee_id: int,
    _admin: User = Depends(require_admin()),
):
    """Get franchisee details."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")
    return await _franchisee_to_response(franchisee)


@router.put("/{franchisee_id}", response_model=FranchiseeResponse)
async def update_franchisee(
    franchisee_id: int,
    body: FranchiseeUpdate,
    admin: User = Depends(require_admin()),
):
    """Update franchisee business details."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    await Franchisee.filter(id=franchisee_id).update(**update_data)
    await franchisee.refresh_from_db()

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.updated",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes=update_data,
    )

    return await _franchisee_to_response(franchisee)


@router.put("/{franchisee_id}/commission")
async def update_commission(
    franchisee_id: int,
    body: CommissionUpdate,
    admin: User = Depends(require_admin()),
):
    """Update franchisee commission rate with audit trail."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    previous = franchisee.commission_percent

    await CommissionAuditLog.create(
        franchisee=franchisee,
        previous_percent=previous,
        new_percent=body.new_percent,
        reason=body.reason,
        effective_from=body.effective_from,
        changed_by=admin,
        notes=body.notes,
    )

    await Franchisee.filter(id=franchisee_id).update(
        commission_percent=body.new_percent,
        commission_effective_from=body.effective_from,
    )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.commission_updated",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"previous": str(previous), "new": str(body.new_percent)},
    )

    return {"message": "Commission updated", "previous": previous, "new": body.new_percent}


@router.put("/{franchisee_id}/tds")
async def update_tds(
    franchisee_id: int,
    body: TDSUpdate,
    admin: User = Depends(require_admin()),
):
    """Update franchisee TDS rate."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    previous = franchisee.tds_rate_percent
    await Franchisee.filter(id=franchisee_id).update(
        tds_rate_percent=body.tds_rate_percent,
    )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.tds_updated",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"previous": str(previous), "new": str(body.tds_rate_percent)},
    )

    return {"message": "TDS rate updated", "previous": previous, "new": body.tds_rate_percent}


@router.get("/{franchisee_id}/commission-history", response_model=List[CommissionAuditResponse])
async def get_commission_history(
    franchisee_id: int,
    _admin: User = Depends(require_admin()),
):
    """Get commission change audit log for a franchisee."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    logs = await CommissionAuditLog.filter(
        franchisee_id=franchisee_id
    ).prefetch_related("changed_by").order_by("-created_at")

    return [
        {
            "id": log.id,
            "previous_percent": log.previous_percent,
            "new_percent": log.new_percent,
            "reason": log.reason.value if hasattr(log.reason, "value") else str(log.reason),
            "effective_from": log.effective_from,
            "notes": log.notes,
            "changed_by_email": log.changed_by.email if log.changed_by else None,
            "created_at": log.created_at,
        }
        for log in logs
    ]


# ─── Station Assignment ─────────────────────────────────────────────

@router.post("/{franchisee_id}/stations")
async def assign_stations(
    franchisee_id: int,
    body: StationAssign,
    admin: User = Depends(require_admin()),
):
    """Assign stations to a franchisee."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    stations = await ChargingStation.filter(id__in=body.station_ids)
    if len(stations) != len(body.station_ids):
        found_ids = {s.id for s in stations}
        missing = [sid for sid in body.station_ids if sid not in found_ids]
        raise HTTPException(status_code=404, detail=f"Stations not found: {missing}")

    # Check for stations already owned by another franchisee
    conflicts = [s for s in stations if s.franchisee_id and s.franchisee_id != franchisee_id]
    if conflicts:
        conflict_ids = [s.id for s in conflicts]
        raise HTTPException(
            status_code=409,
            detail=f"Stations already assigned to another franchisee: {conflict_ids}",
        )

    await ChargingStation.filter(id__in=body.station_ids).update(franchisee_id=franchisee_id)

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.stations_assigned",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"station_ids": body.station_ids},
    )

    return {"message": f"Assigned {len(body.station_ids)} station(s) to franchisee"}


@router.delete("/{franchisee_id}/stations/{station_id}")
async def unassign_station(
    franchisee_id: int,
    station_id: int,
    admin: User = Depends(require_admin()),
):
    """Unassign a station from a franchisee (reverts to VoltLync-owned)."""
    station = await ChargingStation.filter(id=station_id, franchisee_id=franchisee_id).first()
    if not station:
        raise HTTPException(
            status_code=404,
            detail="Station not found or not assigned to this franchisee",
        )

    await ChargingStation.filter(id=station_id).update(franchisee_id=None)

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.station_unassigned",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"station_id": station_id},
    )

    return {"message": f"Station {station_id} unassigned from franchisee"}


@router.get("/{franchisee_id}/stations")
async def get_franchisee_stations(
    franchisee_id: int,
    _admin: User = Depends(require_admin()),
):
    """Get stations assigned to a franchisee."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    stations = await ChargingStation.filter(
        franchisee_id=franchisee_id,
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


# ─── Status Management ───────────────────────────────────────────────

@router.put("/{franchisee_id}/status")
async def update_status(
    franchisee_id: int,
    status: FranchiseeStatusEnum = Query(...),
    reason: Optional[str] = None,
    admin: User = Depends(require_admin()),
):
    """Update franchisee status (activate, suspend, deactivate)."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    update_fields = {"status": status, "status_reason": reason}

    if status == FranchiseeStatusEnum.ACTIVE and not franchisee.activated_at:
        update_fields["activated_at"] = datetime.utcnow()
    elif status == FranchiseeStatusEnum.DEACTIVATED:
        update_fields["deactivated_at"] = datetime.utcnow()

    await Franchisee.filter(id=franchisee_id).update(**update_fields)

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.status_updated",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"status": status.value, "reason": reason},
    )

    return {"message": f"Franchisee status updated to {status.value}"}


# ─── Settlement Management ───────────────────────────────────────────

@router.get("/{franchisee_id}/settlements")
async def list_settlements(
    franchisee_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    _admin: User = Depends(require_admin()),
):
    """List settlement ledger entries for a franchisee."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    query = CommissionLedgerEntry.filter(franchisee_id=franchisee_id)
    if status:
        query = query.filter(settlement_status=status)

    total = await query.count()
    entries = await query.offset((page - 1) * limit).limit(limit).order_by("-created_at")

    return {
        "data": [
            {
                "id": e.id,
                "transaction_id": e.transaction_id,
                "payment_method": e.payment_method,
                "gross_amount": str(e.gross_amount),
                "refund_amount": str(e.refund_amount),
                "pg_fee_amount": str(e.pg_fee_amount),
                "net_amount": str(e.net_amount),
                "gst_collected": str(e.gst_collected),
                "net_excl_gst": str(e.net_excl_gst),
                "commission_percent": str(e.commission_percent),
                "platform_commission": str(e.platform_commission),
                "tds_amount": str(e.tds_amount),
                "transfer_fee": str(e.transfer_fee),
                "franchisee_payout": str(e.franchisee_payout),
                "energy_consumed_kwh": e.energy_consumed_kwh,
                "settlement_status": e.settlement_status.value if hasattr(e.settlement_status, "value") else str(e.settlement_status),
                "razorpay_transfer_id": e.razorpay_transfer_id,
                "failure_reason": e.failure_reason,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/{franchisee_id}/settlements/retry-failed")
async def retry_failed_settlements(
    franchisee_id: int,
    admin: User = Depends(require_admin()),
):
    """Manually retry failed transfers for a franchisee."""
    from services.franchisee_settlement_service import FranchiseeSettlementService

    success, total = await FranchiseeSettlementService.retry_failed_transfers(
        franchisee_id=franchisee_id
    )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.retry_settlements",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"success": success, "total": total},
    )

    return {"message": f"Retried {total} entries, {success} succeeded"}


@router.post("/{franchisee_id}/settlements/{entry_id}/hold")
async def hold_settlement(
    franchisee_id: int,
    entry_id: int,
    admin: User = Depends(require_admin()),
):
    """Put a settlement entry on hold."""
    entry = await CommissionLedgerEntry.filter(
        id=entry_id, franchisee_id=franchisee_id
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Settlement not found")

    await CommissionLedgerEntry.filter(id=entry_id).update(
        settlement_status=SettlementStatusEnum.ON_HOLD,
    )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="settlement.hold",
        entity_type="commission_ledger_entry",
        entity_id=str(entry_id),
        changes={"previous_status": entry.settlement_status.value if hasattr(entry.settlement_status, "value") else str(entry.settlement_status)},
    )

    return {"message": "Settlement placed on hold"}


@router.post("/{franchisee_id}/settlements/{entry_id}/release")
async def release_settlement(
    franchisee_id: int,
    entry_id: int,
    admin: User = Depends(require_admin()),
):
    """Release a held settlement entry back to PENDING."""
    entry = await CommissionLedgerEntry.filter(
        id=entry_id, franchisee_id=franchisee_id,
        settlement_status=SettlementStatusEnum.ON_HOLD,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Held settlement not found")

    await CommissionLedgerEntry.filter(id=entry_id).update(
        settlement_status=SettlementStatusEnum.PENDING,
    )

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="settlement.release",
        entity_type="commission_ledger_entry",
        entity_id=str(entry_id),
        changes={},
    )

    return {"message": "Settlement released to PENDING"}


# ─── Razorpay Route Onboarding ──────────────────────────────────────

@router.post("/{franchisee_id}/onboard-razorpay")
async def onboard_to_razorpay(
    franchisee_id: int,
    admin: User = Depends(require_admin()),
):
    """Create a Razorpay Route linked account for the franchisee."""
    from services.franchisee_onboarding_service import FranchiseeOnboardingService
    from razorpay.errors import (
        BadRequestError as RazorpayBadRequestError,
        ServerError as RazorpayServerError,
        GatewayError as RazorpayGatewayError,
    )

    try:
        result = await FranchiseeOnboardingService.create_linked_account(
            franchisee_id
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RazorpayBadRequestError, RazorpayServerError, RazorpayGatewayError) as e:
        # Razorpay rejected the payload — surface the exact message so the
        # admin UI shows it as a readable 400 instead of Internal Server Error.
        logger.exception(
            "Razorpay rejected onboarding for franchisee %s", franchisee_id
        )
        raise HTTPException(status_code=400, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.razorpay_onboarded",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={"account_id": result.get("id")},
    )

    return result


@router.delete("/{franchisee_id}/razorpay-account")
async def delete_razorpay_account(
    franchisee_id: int,
    admin: User = Depends(require_admin()),
):
    """Hard-delete the franchisee's Razorpay linked account and clear
    local Razorpay state. Refuses if any commission ledger entries
    exist for the franchisee. Idempotent on re-entry."""
    from services.franchisee_onboarding_service import FranchiseeOnboardingService
    from razorpay.errors import (
        BadRequestError as RazorpayBadRequestError,
        ServerError as RazorpayServerError,
        GatewayError as RazorpayGatewayError,
    )

    try:
        result = await FranchiseeOnboardingService.delete_linked_account(
            franchisee_id
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RazorpayBadRequestError, RazorpayServerError, RazorpayGatewayError) as e:
        logger.exception(
            "Razorpay rejected account delete for franchisee %s",
            franchisee_id,
        )
        raise HTTPException(status_code=502, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.razorpay_account_deleted",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes=result,
    )
    return result


class RazorpayApiLogResponse(BaseModel):
    id: int
    created_at: datetime
    method: str
    endpoint: str
    request_body: Optional[dict] = None
    response_status: Optional[int] = None
    response_body: Optional[dict] = None
    success: bool
    error_message: Optional[str] = None
    razorpay_account_id: Optional[str] = None

    class Config:
        from_attributes = True


@router.get(
    "/{franchisee_id}/razorpay-api-logs",
    response_model=List[RazorpayApiLogResponse],
)
async def list_razorpay_api_logs(
    franchisee_id: int,
    limit: int = Query(50, ge=1, le=200),
    _admin: User = Depends(require_admin()),
):
    """Return the most recent outbound Razorpay API audit-log rows for
    this franchisee, newest first. Sensitive fields in the request /
    response bodies are already masked at write time by
    ``RazorpayService._mask_sensitive`` — admins see the redacted form."""
    from models import RazorpayApiLog

    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")

    rows = await RazorpayApiLog.filter(
        franchisee_id=franchisee_id
    ).order_by("-created_at").limit(limit)

    return [
        {
            "id": r.id,
            "created_at": r.created_at,
            "method": r.method,
            "endpoint": r.endpoint,
            "request_body": r.request_body,
            "response_status": r.response_status,
            "response_body": r.response_body,
            "success": r.success,
            "error_message": r.error_message,
            "razorpay_account_id": r.razorpay_account_id,
        }
        for r in rows
    ]


@router.get("/{franchisee_id}/kyc-status")
async def get_kyc_status(
    franchisee_id: int,
    _admin: User = Depends(require_admin()),
):
    """Fetch latest KYC status from Razorpay."""
    from services.franchisee_onboarding_service import FranchiseeOnboardingService

    try:
        return await FranchiseeOnboardingService.refresh_kyc_status(
            franchisee_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Stakeholders + KYC submission ──────────────────────────────────

class StakeholderResidential(BaseModel):
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None  # ISO-2; defaults to "IN" downstream


class StakeholderCreate(BaseModel):
    name: str
    email: EmailStr
    phone_primary: Optional[str] = None
    # Defaults intentionally None so the onboarding service can derive
    # business-type-aware defaults via _relationship_defaults; an explicit
    # bool from the caller still wins.
    relationship_director: Optional[bool] = None
    relationship_executive: Optional[bool] = None
    pan_number: Optional[str] = None
    residential: Optional[StakeholderResidential] = None


class StakeholderUpdate(BaseModel):
    """Partial update on a stakeholder. All fields optional. None values
    are dropped before being sent to Razorpay or persisted locally."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_primary: Optional[str] = None
    relationship_director: Optional[bool] = None
    relationship_executive: Optional[bool] = None
    pan_number: Optional[str] = None
    residential: Optional[StakeholderResidential] = None


class StakeholderResponse(BaseModel):
    id: int
    razorpay_stakeholder_id: Optional[str] = None
    name: str
    email: str
    phone_primary: Optional[str] = None
    relationship_director: bool
    relationship_executive: bool
    pan_number: Optional[str] = None
    residential_street: Optional[str] = None
    residential_city: Optional[str] = None
    residential_state: Optional[str] = None
    residential_postal_code: Optional[str] = None
    residential_country: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReconcileRequest(BaseModel):
    razorpay_product_id: Optional[str] = None
    razorpay_stakeholder_ids: Optional[List[str]] = None


def _stakeholder_to_response(s: FranchiseeStakeholder) -> dict:
    return {
        "id": s.id,
        "razorpay_stakeholder_id": s.razorpay_stakeholder_id,
        "name": s.name,
        "email": s.email,
        "phone_primary": s.phone_primary,
        "relationship_director": s.relationship_director,
        "relationship_executive": s.relationship_executive,
        "pan_number": s.pan_number,
        "residential_street": s.residential_street,
        "residential_city": s.residential_city,
        "residential_state": s.residential_state,
        "residential_postal_code": s.residential_postal_code,
        "residential_country": s.residential_country,
        "created_at": s.created_at,
    }


@router.get("/{franchisee_id}/stakeholders", response_model=List[StakeholderResponse])
async def list_stakeholders(
    franchisee_id: int,
    _admin: User = Depends(require_admin()),
):
    """List stakeholders registered for a franchisee."""
    franchisee = await Franchisee.filter(id=franchisee_id).first()
    if not franchisee:
        raise HTTPException(status_code=404, detail="Franchisee not found")
    rows = await FranchiseeStakeholder.filter(
        franchisee_id=franchisee_id
    ).order_by("id")
    return [_stakeholder_to_response(s) for s in rows]


@router.post("/{franchisee_id}/stakeholders", response_model=StakeholderResponse)
async def create_stakeholder(
    franchisee_id: int,
    body: StakeholderCreate,
    admin: User = Depends(require_admin()),
):
    """Create a stakeholder on Razorpay + persist locally."""
    from services.franchisee_onboarding_service import FranchiseeOnboardingService

    try:
        row = await FranchiseeOnboardingService.add_stakeholder(
            franchisee_id, body.model_dump(exclude_none=True)
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RazorpayBadRequestError, RazorpayServerError, RazorpayGatewayError) as e:
        logger.exception(
            "Razorpay rejected stakeholder create for franchisee %s", franchisee_id
        )
        raise HTTPException(status_code=400, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.stakeholder_created",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={
            "stakeholder_id": row.id,
            "razorpay_stakeholder_id": row.razorpay_stakeholder_id,
        },
    )
    return _stakeholder_to_response(row)


@router.put(
    "/{franchisee_id}/stakeholders/{stakeholder_id}",
    response_model=StakeholderResponse,
)
async def update_stakeholder(
    franchisee_id: int,
    stakeholder_id: int,
    body: StakeholderUpdate,
    admin: User = Depends(require_admin()),
):
    """PATCH a stakeholder on Razorpay + persist locally. Only fields the
    caller actually provides are updated; None values are dropped."""
    from services.franchisee_onboarding_service import FranchiseeOnboardingService

    payload = body.model_dump(exclude_none=True)
    try:
        row = await FranchiseeOnboardingService.update_stakeholder(
            franchisee_id, stakeholder_id, payload
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RazorpayBadRequestError, RazorpayServerError, RazorpayGatewayError) as e:
        logger.exception(
            "Razorpay rejected stakeholder update for franchisee %s",
            franchisee_id,
        )
        raise HTTPException(status_code=400, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.stakeholder_updated",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={
            "stakeholder_id": stakeholder_id,
            "fields": list(payload.keys()),
        },
    )
    return _stakeholder_to_response(row)


@router.post("/{franchisee_id}/submit-kyc")
async def submit_kyc(
    franchisee_id: int,
    admin: User = Depends(require_admin()),
):
    """Ensure product config + submit bank settlements. Returns the
    resulting ``activation_status`` and outstanding ``requirements``
    from Razorpay so the admin UI can show what (if anything) Razorpay
    is waiting on next."""
    from services.franchisee_onboarding_service import FranchiseeOnboardingService

    try:
        result = await FranchiseeOnboardingService.submit_kyc(franchisee_id)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (RazorpayBadRequestError, RazorpayServerError, RazorpayGatewayError) as e:
        logger.exception(
            "Razorpay rejected KYC submit for franchisee %s", franchisee_id
        )
        raise HTTPException(status_code=400, detail=f"Razorpay: {e}")

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.kyc_submitted",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes={
            "product_id": result.get("product_id"),
            "activation_status": result.get("activation_status"),
            "requirements_count": len(result.get("requirements") or []),
        },
    )
    return result


@router.post("/{franchisee_id}/reconcile-razorpay")
async def reconcile_razorpay(
    franchisee_id: int,
    body: ReconcileRequest,
    admin: User = Depends(require_admin()),
):
    """One-off reconciliation for accounts pushed to Razorpay outside
    our normal flow (staging account ``acc_Sg73UwyOU3jziR`` is the
    motivating example). Stores ``razorpay_product_id`` on the
    franchisee and mirrors existing stakeholders into our local table
    without re-creating them on Razorpay.
    """
    from services.franchisee_onboarding_service import FranchiseeOnboardingService

    try:
        result = await FranchiseeOnboardingService.reconcile_razorpay(
            franchisee_id,
            razorpay_product_id=body.razorpay_product_id,
            razorpay_stakeholder_ids=body.razorpay_stakeholder_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="franchisee.razorpay_reconciled",
        entity_type="franchisee",
        entity_id=str(franchisee_id),
        changes=result,
    )
    return result
