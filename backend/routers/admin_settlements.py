# routers/admin_settlements.py — admin views across all franchisees' settlements.
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_middleware import require_admin
from crud import log_audit_event
from models import (
    CommissionLedgerEntry,
    Franchisee,
    SettlementStatusEnum,
    User,
)
from services.stuck_payout_detector import build_stuck_filter


router = APIRouter(
    prefix="/api/admin/settlements",
    tags=["Settlement Operations"],
)


MAX_TRANSFER_RETRIES = int(os.getenv("MAX_TRANSFER_RETRIES", "3"))
DEFAULT_STUCK_HOURS = int(os.getenv("STUCK_PAYOUT_THRESHOLD_HOURS", "24"))
MIN_TRANSFER_AMOUNT = Decimal(os.getenv("MINIMUM_TRANSFER_AMOUNT", "1.00"))

# Source statuses each terminal-resolution action accepts. Mirror the
# permissive rules from ADR 0007 — anything not already terminal-good or
# terminal-written-off.
_BELOW_THRESHOLD_SOURCES = {
    SettlementStatusEnum.PENDING,
    SettlementStatusEnum.FAILED,
    SettlementStatusEnum.ON_HOLD,
}
_MANUAL_SETTLE_SOURCES = {
    SettlementStatusEnum.PENDING,
    SettlementStatusEnum.TRANSFER_INITIATED,
    SettlementStatusEnum.TRANSFER_PROCESSED,
    SettlementStatusEnum.FAILED,
    SettlementStatusEnum.ON_HOLD,
}


class ManualSettleBody(BaseModel):
    note: str = Field(..., min_length=3, max_length=2000)


def _status_value(s) -> str:
    return s.value if hasattr(s, "value") else str(s)


@router.get("/stuck")
async def list_stuck_settlements(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    older_than_hours: int = Query(DEFAULT_STUCK_HOURS, ge=1, le=720),
    status: Optional[str] = None,
    _admin: User = Depends(require_admin()),
):
    """Settlement entries that look stuck — across all franchisees.

    Predicate is the same one used by the background
    ``stuck_payout_detector`` sweep (``build_stuck_filter``).
    """
    query = CommissionLedgerEntry.filter(
        build_stuck_filter(older_than_hours, MAX_TRANSFER_RETRIES)
    )
    if status:
        query = query.filter(settlement_status=status)

    total = await query.count()
    entries = (
        await query.offset((page - 1) * limit)
        .limit(limit)
        .order_by("-created_at")
        .prefetch_related("franchisee")
    )

    franchisee_ids = {e.franchisee_id for e in entries}
    franchisees = await Franchisee.filter(id__in=franchisee_ids)
    name_by_id = {f.id: f.business_name for f in franchisees}

    return {
        "data": [
            {
                "id": e.id,
                "franchisee_id": e.franchisee_id,
                "franchisee_business_name": name_by_id.get(e.franchisee_id, ""),
                "transaction_id": e.transaction_id,
                "settlement_status": _status_value(e.settlement_status),
                "franchisee_payout": str(e.franchisee_payout),
                "gross_amount": str(e.gross_amount),
                "retry_count": e.retry_count,
                "failure_reason": e.failure_reason,
                "razorpay_payment_id": e.razorpay_payment_id,
                "razorpay_transfer_id": e.razorpay_transfer_id,
                "created_at": e.created_at.isoformat(),
                "transfer_initiated_at": (
                    e.transfer_initiated_at.isoformat()
                    if e.transfer_initiated_at
                    else None
                ),
            }
            for e in entries
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "older_than_hours": older_than_hours,
    }


@router.post("/{entry_id}/mark-below-threshold")
async def mark_below_threshold(
    entry_id: int,
    admin: User = Depends(require_admin()),
):
    """Mark a sub-floor settlement entry terminal as ``BELOW_THRESHOLD``.

    Requires ``franchisee_payout < MIN_TRANSFER_AMOUNT`` — Razorpay Route
    refuses transfers below ₹1.00, so these entries will never settle via
    the API. Idempotent: re-calling on an already-``BELOW_THRESHOLD`` row
    is a no-op (200, no second audit row). See ADR 0007.
    """
    entry = await CommissionLedgerEntry.filter(id=entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Settlement entry not found")

    if entry.settlement_status == SettlementStatusEnum.BELOW_THRESHOLD:
        return {
            "message": "Already marked BELOW_THRESHOLD",
            "settlement_status": _status_value(entry.settlement_status),
        }
    if entry.settlement_status not in _BELOW_THRESHOLD_SOURCES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot mark BELOW_THRESHOLD from "
                f"{_status_value(entry.settlement_status)}"
            ),
        )
    if entry.franchisee_payout >= MIN_TRANSFER_AMOUNT:
        raise HTTPException(
            status_code=422,
            detail=(
                f"franchisee_payout {entry.franchisee_payout} is not below "
                f"the {MIN_TRANSFER_AMOUNT} threshold"
            ),
        )

    previous_status = _status_value(entry.settlement_status)
    await CommissionLedgerEntry.filter(id=entry_id).update(
        settlement_status=SettlementStatusEnum.BELOW_THRESHOLD,
    )
    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="settlement.mark_below_threshold",
        entity_type="commission_ledger_entry",
        entity_id=str(entry_id),
        changes={
            "previous_status": previous_status,
            "franchisee_payout": str(entry.franchisee_payout),
            "min_transfer_amount": str(MIN_TRANSFER_AMOUNT),
        },
    )
    return {
        "message": "Marked BELOW_THRESHOLD",
        "settlement_status": SettlementStatusEnum.BELOW_THRESHOLD.value,
    }


@router.post("/{entry_id}/mark-settled")
async def mark_settled(
    entry_id: int,
    body: ManualSettleBody,
    admin: User = Depends(require_admin()),
):
    """Mark a settlement entry terminal as ``SETTLED`` with an admin note.

    For entries resolved out-of-band (bank transfer, refund of a stuck
    payment, etc.). Sets ``settled_at = now()`` only if previously NULL —
    idempotent re-clicks preserve the original timestamp. Razorpay ID
    fields are left untouched (manual ⇒ no Razorpay transfer). The note
    is mandatory (min 3 chars) and is stored in the audit row's
    ``changes`` JSON. See ADR 0007.
    """
    entry = await CommissionLedgerEntry.filter(id=entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Settlement entry not found")

    if entry.settlement_status == SettlementStatusEnum.SETTLED:
        return {
            "message": "Already SETTLED",
            "settlement_status": _status_value(entry.settlement_status),
        }
    if entry.settlement_status not in _MANUAL_SETTLE_SOURCES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot manually settle from "
                f"{_status_value(entry.settlement_status)}"
            ),
        )

    previous_status = _status_value(entry.settlement_status)
    updates = {"settlement_status": SettlementStatusEnum.SETTLED}
    if entry.settled_at is None:
        updates["settled_at"] = datetime.now(timezone.utc)
    await CommissionLedgerEntry.filter(id=entry_id).update(**updates)
    await log_audit_event(
        actor_type="admin",
        actor=admin,
        action="settlement.manual_settle",
        entity_type="commission_ledger_entry",
        entity_id=str(entry_id),
        changes={
            "previous_status": previous_status,
            "note": body.note,
            "franchisee_payout": str(entry.franchisee_payout),
        },
    )
    return {
        "message": "Marked SETTLED",
        "settlement_status": SettlementStatusEnum.SETTLED.value,
    }
