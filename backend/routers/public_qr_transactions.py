"""Public endpoint for QR payment users to look up transaction history by UPI ID"""
import re
import time
import uuid
import logging
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Optional

from models import QRPayment, QRPaymentStatusEnum
from redis_manager import redis_manager
from services.razorpay_service import razorpay_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public/qr-transactions", tags=["Public QR Transactions"])

# UPI VPA: alphanumeric start, optional dots/hyphens/underscores, @ followed by bank code (2+ alpha chars)
VPA_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.\-_]{0,253}@[a-zA-Z][a-zA-Z0-9]{1,}$")

# Simple in-memory rate limiter: {ip: [timestamp, ...]}
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 20  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds

VERIFICATION_TOKEN_TTL = 600  # 10 minutes


def _check_rate_limit(client_ip: str):
    """Enforce per-IP rate limiting. Raises 429 if exceeded."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    _rate_limit_store[client_ip] = [
        ts for ts in _rate_limit_store[client_ip] if ts > window_start
    ]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    _rate_limit_store[client_ip].append(now)


def _validate_vpa_format(vpa: str) -> str:
    """Normalize and validate VPA format. Returns lowercased VPA or raises 400."""
    vpa = vpa.lower().strip()
    if not VPA_PATTERN.match(vpa):
        raise HTTPException(status_code=400, detail="Invalid UPI ID format")
    return vpa


def _mask_name(name: str) -> str:
    """Mask a name: 'Gaurav Kumar' -> 'G**** K****'"""
    words = name.strip().split()
    masked_parts = []
    for word in words:
        if len(word) <= 1:
            masked_parts.append(word)
        else:
            masked_parts.append(word[0] + "*" * (len(word) - 1))
    return " ".join(masked_parts)


class LookupRequest(BaseModel):
    vpa: str


class VerifyRequest(BaseModel):
    vpa: str
    full_name: str


@router.post("/lookup")
async def lookup_vpa(request: Request, body: LookupRequest):
    """Look up a VPA via Razorpay and return a masked account holder name."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    vpa = _validate_vpa_format(body.vpa)

    # Check if VPA has any QR payments before calling Razorpay
    has_payments = await QRPayment.filter(customer_vpa=vpa).exists()
    if not has_payments:
        raise HTTPException(status_code=404, detail="No transactions found for this UPI ID")

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Payment service unavailable")

    result = razorpay_service.validate_vpa(vpa)
    if not result or not result.get("success"):
        raise HTTPException(status_code=404, detail="Could not verify this UPI ID")

    customer_name = result.get("customer_name", "")
    if not customer_name:
        raise HTTPException(status_code=404, detail="Could not verify this UPI ID")

    masked = _mask_name(customer_name)
    logger.info(f"VPA lookup: vpa=***{vpa[-6:]}, masked_name={masked}")

    return {"masked_name": masked}


@router.post("/verify")
async def verify_vpa_ownership(request: Request, body: VerifyRequest):
    """Verify VPA ownership by matching the full name against Razorpay's records."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    vpa = _validate_vpa_format(body.vpa)
    full_name = body.full_name.strip()

    if not full_name or len(full_name) < 2:
        raise HTTPException(status_code=400, detail="Please enter a valid name")

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Payment service unavailable")

    result = razorpay_service.validate_vpa(vpa)
    if not result or not result.get("success"):
        raise HTTPException(status_code=404, detail="Could not verify this UPI ID")

    customer_name = result.get("customer_name", "")
    if not customer_name:
        raise HTTPException(status_code=403, detail="Verification failed")

    # Case-insensitive comparison
    if full_name.lower() != customer_name.lower():
        logger.info(f"VPA verify failed: vpa=***{vpa[-6:]}")
        raise HTTPException(status_code=403, detail="Name does not match. Please try again.")

    # Generate verification token
    token = str(uuid.uuid4())
    await redis_manager.set_qr_txn_token(token, vpa, ttl=VERIFICATION_TOKEN_TTL)

    logger.info(f"VPA verified: vpa=***{vpa[-6:]}, token issued")
    return {"token": token, "expires_in": VERIFICATION_TOKEN_TTL}


@router.get("")
async def get_transactions_by_vpa(
    request: Request,
    token: str = Query(..., description="Verification token from /verify"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    status: Optional[str] = None,
):
    """Look up QR payment transaction history (requires verification token)."""
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    # Validate token
    vpa = await redis_manager.get_qr_txn_token(token)
    if not vpa:
        raise HTTPException(status_code=401, detail="Session expired. Please verify again.")

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
            "platform_fee": str(p.platform_fee) if p.platform_fee else None,
            "refund_amount": str(p.refund_amount) if p.refund_amount else None,
            "charger_name": charger.name if charger else None,
            "duration_minutes": duration_minutes,
            "start_time": txn.start_time.isoformat() if txn and txn.start_time else None,
            "end_time": txn.end_time.isoformat() if txn and txn.end_time else None,
            "failure_reason": p.failure_reason,
        })

    masked = f"***{vpa[-6:]}" if len(vpa) > 6 else "***"
    logger.info(f"QR txn lookup: vpa={masked}, results={total}, page={page}")

    return {"data": results, "total": total, "page": page, "limit": limit}
