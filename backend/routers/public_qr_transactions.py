"""Public endpoint for QR payment users to look up transaction history by UPI ID"""
import re
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional

from models import QRPayment, QRPaymentStatusEnum
from redis_manager import redis_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public/qr-transactions", tags=["Public QR Transactions"])

# UPI VPA: alphanumeric start, optional dots/hyphens/underscores, @ followed by bank code (2+ alpha chars)
VPA_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.\-_]{0,253}@[a-zA-Z][a-zA-Z0-9]{1,}$")

RATE_LIMIT_MAX = 20  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds


async def _check_rate_limit(client_ip: str):
    """Enforce per-IP rate limiting via Redis. Raises 429 if exceeded."""
    key = f"public_qr_transactions:{client_ip}"
    allowed = await redis_manager.rate_limit_check(key, RATE_LIMIT_MAX, RATE_LIMIT_WINDOW)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")


def _validate_vpa_format(vpa: str) -> str:
    """Normalize and validate VPA format. Returns lowercased VPA or raises 400."""
    vpa = vpa.lower().strip()
    if not VPA_PATTERN.match(vpa):
        raise HTTPException(status_code=400, detail="Invalid UPI ID format")
    return vpa


@router.get("")
async def get_transactions_by_vpa(
    request: Request,
    vpa: str = Query(..., description="UPI VPA to look up transactions for"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    status: Optional[str] = None,
):
    """Look up QR payment transaction history by VPA."""
    client_ip = request.client.host if request.client else "unknown"
    await _check_rate_limit(client_ip)

    vpa = _validate_vpa_format(vpa)

    query = QRPayment.filter(customer_vpa=vpa).prefetch_related("charger", "transaction")

    if status:
        try:
            status_enum = QRPaymentStatusEnum(status)
            query = query.filter(status=status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid status filter")

    total = await query.count()
    payments = await query.order_by("-created_at").offset((page - 1) * limit).limit(limit)

    results = []
    for p in payments:
        txn = p.transaction if p.transaction_id else None
        charger = p.charger

        duration_minutes = None
        if txn and txn.start_time and txn.end_time:
            delta = txn.end_time - txn.start_time
            duration_minutes = round(delta.total_seconds() / 60, 1)

        results.append({
            "id": p.id,
            "created_at": p.created_at.isoformat(),
            "amount_paid": str(p.amount_paid),
            "status": p.status.value,
            "energy_consumed_kwh": txn.energy_consumed_kwh if txn else None,
            "energy_cost": str(p.energy_cost) if p.energy_cost else None,
            "gst_amount": str(p.gst_amount) if p.gst_amount else None,
            "platform_fee": str(p.platform_fee) if p.platform_fee else None,
            "razorpay_commission": str(p.razorpay_commission) if p.razorpay_commission else None,
            "razorpay_gst": str(p.razorpay_gst) if p.razorpay_gst else None,
            "fee_source": p.fee_source,
            "refund_amount": str(p.refund_amount) if p.refund_amount else None,
            "charger_name": charger.name if charger else None,
            "duration_minutes": duration_minutes,
            "start_time": txn.start_time.isoformat() if txn and txn.start_time else None,
            "end_time": txn.end_time.isoformat() if txn and txn.end_time else None,
            "failure_reason": p.failure_reason,
        })

    masked_vpa = f"***{vpa[-6:]}" if len(vpa) > 6 else "***"
    logger.info(f"QR txn lookup: vpa={masked_vpa}, results={total}, page={page}")

    return {"data": results, "total": total, "page": page, "limit": limit}
