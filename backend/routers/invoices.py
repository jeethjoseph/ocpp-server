"""Invoice API endpoints.

Handles GST invoice listing and PDF download for admin, franchisee, and users.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
import io

from models import GSTInvoice, CommissionLedgerEntry, User
from auth_middleware import (
    require_admin,
    require_franchisee,
    require_user_or_admin,
    get_current_user_with_db,
)
from services.invoice_service import InvoiceService

logger = logging.getLogger("ocpp-server")

router = APIRouter(tags=["Invoices"])


# ─── Admin invoice endpoints ─────────────────────────────────────────

@router.get("/api/admin/invoices")
async def admin_list_invoices(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    franchisee_id: Optional[int] = None,
    _admin: User = Depends(require_admin()),
):
    """List GST invoices (admin view, all or filtered by franchisee)."""
    query = GSTInvoice.all()
    if franchisee_id is not None:
        query = query.filter(franchisee_id=franchisee_id)

    total = await query.count()
    invoices = await query.offset((page - 1) * limit).limit(limit).order_by(
        "-created_at"
    )

    return {
        "data": [_invoice_to_dict(inv) for inv in invoices],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/api/admin/invoices/{invoice_id}/pdf")
async def admin_download_invoice_pdf(
    invoice_id: int,
    _admin: User = Depends(require_admin()),
):
    """Download invoice PDF (admin)."""
    return await _serve_invoice_pdf(invoice_id)


# ─── Franchisee portal invoice endpoints ─────────────────────────────

@router.get("/api/franchisee/invoices")
async def franchisee_list_invoices(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    auth=Depends(require_franchisee()),
):
    """List GST invoices for own stations."""
    _, franchisee = auth
    query = GSTInvoice.filter(franchisee_id=franchisee.id)

    total = await query.count()
    invoices = await query.offset((page - 1) * limit).limit(limit).order_by(
        "-created_at"
    )

    return {
        "data": [_invoice_to_dict(inv) for inv in invoices],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/api/franchisee/invoices/{invoice_id}/pdf")
async def franchisee_download_invoice_pdf(
    invoice_id: int,
    auth=Depends(require_franchisee()),
):
    """Download invoice PDF (franchisee -- own invoices only)."""
    _, franchisee = auth
    invoice = await GSTInvoice.filter(
        id=invoice_id, franchisee_id=franchisee.id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return await _serve_invoice_pdf(invoice_id)


# ─── Transaction-level invoice download ──────────────────────────────

@router.get("/api/transactions/{transaction_id}/invoice/pdf")
async def download_transaction_invoice_pdf(
    transaction_id: int,
    user: User = Depends(get_current_user_with_db),
):
    """Download invoice PDF by transaction ID (any authenticated user)."""
    invoice = await GSTInvoice.filter(
        transaction_id=transaction_id
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found for this transaction")
    return await _serve_invoice_pdf(invoice.id)


# ─── Helpers ─────────────────────────────────────────────────────────

def _invoice_to_dict(inv: GSTInvoice) -> dict:
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "supplier_name": inv.supplier_name,
        "customer_name": inv.customer_name,
        "customer_identifier": inv.customer_identifier,
        "energy_consumed_kwh": inv.energy_consumed_kwh,
        "total_amount": str(inv.total_amount),
        "payment_method": inv.payment_method,
        "transaction_id": inv.transaction_id,
        "franchisee_id": inv.franchisee_id,
        "created_at": inv.created_at.isoformat(),
    }


async def _serve_invoice_pdf(invoice_id: int) -> StreamingResponse:
    invoice = await GSTInvoice.filter(id=invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_bytes = InvoiceService.generate_pdf(invoice)

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="invoice_{invoice.invoice_number.replace("/", "_")}.pdf"',
        },
    )
