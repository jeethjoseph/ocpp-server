"""Public endpoint for QR payment users to look up transaction history by UPI ID"""
import logging
from decimal import Decimal
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional

from core.validators import VPA_PATTERN
from models import GSTInvoice, QRPayment, QRPaymentStatusEnum
from redis_manager import redis_manager
from routers.invoices import serve_invoice_pdf
from services.invoice_service import build_invoice_line_items
from services.qr_payment_service import is_below_minimum_reason

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


def _customer_breakdown(payment, txn, invoice):
    """Reconciled customer-facing billing breakdown, identical to the GST invoice.

    Returns tax-inclusive per-line `line_items` (Energy, Gateway charges) plus a
    `bill_total` — the same line totals the itemised PDF shows (ADR 0024), summing
    to `amount_paid − refund`. Sources from the invoice (the reconciled source of
    truth) when present, else falls back to the synthetic gateway split so we
    never expose the actual Razorpay commission (`qr_payment.platform_fee`, ADR
    0001). The flat `energy_cost` / `gst_amount` / `gateway_fee` fields are kept
    for backward compatibility. Energy is shown at full stored precision.
    """
    if invoice is not None:
        items = [
            {"label": it["label"], "amount": str(it["line_total"])}
            for it in build_invoice_line_items(invoice)
        ]
        return {
            "energy_consumed_kwh": invoice.energy_consumed_kwh,
            "energy_cost": str(invoice.energy_taxable_value),
            "gst_amount": str(invoice.total_tax),
            "gateway_fee": str(invoice.gateway_charges) if invoice.gateway_charges else None,
            "line_items": items,
            "bill_total": str(invoice.total_amount),
        }
    if txn is not None and txn.energy_charge is not None:
        # Gateway is the ACTUAL Razorpay fee stored on the QR payment (ADR 0026),
        # not a synthetic split of amount_paid.
        gateway_taxable = payment.razorpay_commission or Decimal("0")
        gateway_gst = payment.razorpay_gst or Decimal("0")
        gst_total = (txn.gst_amount or Decimal("0")) + gateway_gst
        energy_incl = (txn.energy_charge or Decimal("0")) + (txn.gst_amount or Decimal("0"))
        gateway_incl = gateway_taxable + gateway_gst
        items = [{"label": "Energy", "amount": str(energy_incl)}]
        if gateway_incl > 0:
            items.append({"label": "Gateway charges", "amount": str(gateway_incl)})
        return {
            "energy_consumed_kwh": txn.energy_consumed_kwh,
            "energy_cost": str(txn.energy_charge),
            "gst_amount": str(gst_total),
            "gateway_fee": str(gateway_taxable),
            "line_items": items,
            "bill_total": str(energy_incl + gateway_incl),
        }
    return {
        "energy_consumed_kwh": txn.energy_consumed_kwh if txn else None,
        "energy_cost": None,
        "gst_amount": None,
        "gateway_fee": None,
        "line_items": [],
        "bill_total": None,
    }


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

    # Bulk-load the reconciled invoices so the card mirrors the PDF exactly.
    txn_ids = [p.transaction_id for p in payments if p.transaction_id]
    invoices_by_txn = {}
    if txn_ids:
        for inv in await GSTInvoice.filter(transaction_id__in=txn_ids):
            invoices_by_txn[inv.transaction_id] = inv

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
            # Reconciled breakdown identical to the GST invoice — energy_cost +
            # gateway_fee + gst_amount == amount_paid − refund. Never exposes the
            # actual Razorpay commission (ADR 0001).
            **_customer_breakdown(p, txn, invoices_by_txn.get(p.transaction_id)),
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
            # Benign sub-₹1 forfeit (Razorpay's floor) — not an operational
            # failure. Lets the UI render it neutrally instead of as an error.
            "refund_below_minimum": (
                p.status == QRPaymentStatusEnum.REFUND_FAILED
                and is_below_minimum_reason(p.failure_reason)
            ),
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
