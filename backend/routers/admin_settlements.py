# routers/admin_settlements.py — admin views across all franchisees' settlements.
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth_middleware import require_admin
from models import (
    CommissionLedgerEntry,
    Franchisee,
    User,
)
from services.stuck_payout_detector import build_stuck_filter


router = APIRouter(
    prefix="/api/admin/settlements",
    tags=["Settlement Operations"],
)


MAX_TRANSFER_RETRIES = int(os.getenv("MAX_TRANSFER_RETRIES", "3"))
DEFAULT_STUCK_HOURS = int(os.getenv("STUCK_PAYOUT_THRESHOLD_HOURS", "24"))


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
                "settlement_status": (
                    e.settlement_status.value
                    if hasattr(e.settlement_status, "value")
                    else str(e.settlement_status)
                ),
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
