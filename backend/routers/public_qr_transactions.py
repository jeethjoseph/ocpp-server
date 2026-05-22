"""Public endpoint for QR payment users to look up transaction history by UPI ID"""
import logging
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional

from core.validators import VPA_PATTERN
from models import GSTInvoice, QRPayment, QRPaymentStatusEnum
from redis_manager import redis_manager
from routers.invoices import serve_invoice_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public/qr-transactions", tags=["Public QR Transactions"])

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

    query = QRPayment.filter(customer_vpa=vpa).prefetch_related(
        "charger__station__franchisee", "transaction",
    )

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
        station = charger.station if charger else None
        franchisee = station.franchisee if station else None

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
            "platform_fee": str(p.platform_fee) if p.platform_fee is not None else None,
            "razorpay_commission": str(p.razorpay_commission) if p.razorpay_commission is not None else None,
            "razorpay_gst": str(p.razorpay_gst) if p.razorpay_gst is not None else None,
            "fee_source": p.fee_source,
            "refund_amount": str(p.refund_amount) if p.refund_amount else None,
            "razorpay_refund_id": p.razorpay_refund_id,
            "razorpay_refund_speed_processed": p.razorpay_refund_speed_processed,
            "refund_processed_at": p.refund_processed_at.isoformat() if p.refund_processed_at else None,
            "refund_failure_reason": p.refund_failure_reason,
            "charger_name": charger.name if charger else None,
            "station_name": station.name if station else None,
            "franchisee_name": franchisee.business_name if franchisee else None,
            "duration_minutes": duration_minutes,
            "start_time": txn.start_time.isoformat() if txn and txn.start_time else None,
            "end_time": txn.end_time.isoformat() if txn and txn.end_time else None,
            "failure_reason": p.failure_reason,
        })

    masked_vpa = f"***{vpa[-6:]}" if len(vpa) > 6 else "***"
    logger.info(f"QR txn lookup: vpa={masked_vpa}, results={total}, page={page}")

    return {"data": results, "total": total, "page": page, "limit": limit}


@router.get("/{qr_payment_id}/invoice/pdf")
async def public_invoice_pdf(
    qr_payment_id: int,
    request: Request,
    vpa: str = Query(..., description="Customer's UPI VPA — must match the QR payment"),
):
    """Public PDF download — customer authenticates by knowing their own VPA.

    Rate-limited per IP. Same trust model as the QR-transactions list endpoint:
    the VPA is treated as the implicit credential. We don't leak whether a
    qr_payment exists for an unknown id vs. wrong VPA — both return 404.
    """
    client_ip = request.client.host if request.client else "unknown"
    await _check_rate_limit(client_ip)
    vpa = _validate_vpa_format(vpa)

    qr_payment = await QRPayment.filter(id=qr_payment_id).first()
    if not qr_payment or (qr_payment.customer_vpa or "").lower() != vpa.lower():
        # Indistinguishable error so we don't disclose whether the id exists.
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not qr_payment.transaction_id:
        raise HTTPException(status_code=404, detail="Invoice not available for this payment")

    invoice = await GSTInvoice.filter(transaction_id=qr_payment.transaction_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not available for this payment")

    masked_vpa = f"***{vpa[-6:]}" if len(vpa) > 6 else "***"
    logger.info(f"Public invoice PDF: qr_payment_id={qr_payment_id}, vpa={masked_vpa}")
    return await serve_invoice_pdf(invoice.id)
