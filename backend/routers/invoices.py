"""Invoice API endpoints.

Handles GST invoice listing and PDF download for admin, franchisee, and users.
Admin endpoints additionally support a summary aggregate and a streaming CSV
export for GSTR-1 reconciliation.
"""

import asyncio
import csv
import io
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse, StreamingResponse
from tortoise.expressions import Q
from tortoise.functions import Sum, Count

from models import GSTInvoice, User
from auth_middleware import (
    require_admin,
    require_franchisee,
    get_current_user_with_db,
)
from services.invoice_service import InvoiceService
from services import s3_service
from services.monitoring_service import MetricsCollector

logger = logging.getLogger("ocpp-server")

router = APIRouter(tags=["Invoices"])


# ─── Date parsing (mirrors backend/routers/logs.py:_parse_date) ──────

def _parse_date(value: str, field_name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Use ISO 8601 with timezone (e.g. 2026-03-10T00:00:00Z)",
        )
    if dt.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must include timezone info (e.g. append 'Z' for UTC). Got: {value}",
        )
    return dt


# ─── Shared filter builder ───────────────────────────────────────────

def _build_filter_query(
    franchisee_id: Optional[int],
    financial_year: Optional[str],
    series: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    place_of_supply_state_code: Optional[str],
    is_inter_state: Optional[bool],
    q: Optional[str],
):
    query = GSTInvoice.all()
    if franchisee_id is not None:
        query = query.filter(franchisee_id=franchisee_id)
    if financial_year:
        query = query.filter(financial_year=financial_year)
    if series:
        query = query.filter(series=series)
    if place_of_supply_state_code:
        query = query.filter(place_of_supply_state_code=place_of_supply_state_code)
    if is_inter_state is not None:
        query = query.filter(is_inter_state=is_inter_state)
    if start_date:
        query = query.filter(invoice_date__gte=_parse_date(start_date, "start_date"))
    if end_date:
        query = query.filter(invoice_date__lte=_parse_date(end_date, "end_date"))
    if q:
        like = f"%{q}%"
        query = query.filter(
            Q(invoice_number__icontains=q)
            | Q(customer_identifier__icontains=q)
            | Q(customer_name__icontains=q)
        )
        _ = like  # quiet linters; like reserved for future raw SQL paths
    return query


# ─── Admin invoice endpoints ─────────────────────────────────────────

@router.get("/api/admin/invoices")
async def admin_list_invoices(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    franchisee_id: Optional[int] = None,
    financial_year: Optional[str] = None,
    series: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    place_of_supply_state_code: Optional[str] = None,
    is_inter_state: Optional[bool] = None,
    q: Optional[str] = None,
    _admin: User = Depends(require_admin()),
):
    """List GST invoices for the admin filings view.

    Filters compose. Date range applies to ``invoice_date`` to match the
    GSTR-1 filing periodicity (an invoice belongs to the month it was issued,
    not the month the session ran).
    """
    query = _build_filter_query(
        franchisee_id, financial_year, series, start_date, end_date,
        place_of_supply_state_code, is_inter_state, q,
    )

    total = await query.count()
    invoices = await query.offset((page - 1) * limit).limit(limit).order_by(
        "-invoice_date", "-id"
    )

    return {
        "data": [_invoice_to_dict(inv) for inv in invoices],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/api/admin/invoices/summary")
async def admin_invoices_summary(
    franchisee_id: Optional[int] = None,
    financial_year: Optional[str] = None,
    series: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    place_of_supply_state_code: Optional[str] = None,
    is_inter_state: Optional[bool] = None,
    q: Optional[str] = None,
    _admin: User = Depends(require_admin()),
):
    """Aggregates over the filtered invoice set for the GST filings header."""
    query = _build_filter_query(
        franchisee_id, financial_year, series, start_date, end_date,
        place_of_supply_state_code, is_inter_state, q,
    )

    # Pull only the columns we need to aggregate — keeps memory flat even
    # without DB-side SUM(). Tortoise's annotate aggregates don't compose
    # cleanly with our chained .filter() above, so iterate the values dicts.
    rows = await query.values(
        "series",
        "total_taxable_value",
        "cgst_amount",
        "sgst_amount",
        "igst_amount",
        "total_tax",
        "total_amount",
    )

    totals = {
        "count": len(rows),
        "total_taxable_value": Decimal("0"),
        "total_cgst": Decimal("0"),
        "total_sgst": Decimal("0"),
        "total_igst": Decimal("0"),
        "total_tax": Decimal("0"),
        "total_amount": Decimal("0"),
    }
    by_series: dict[str, int] = {}
    for r in rows:
        totals["total_taxable_value"] += r["total_taxable_value"] or Decimal("0")
        totals["total_cgst"] += r["cgst_amount"] or Decimal("0")
        totals["total_sgst"] += r["sgst_amount"] or Decimal("0")
        totals["total_igst"] += r["igst_amount"] or Decimal("0")
        totals["total_tax"] += r["total_tax"] or Decimal("0")
        totals["total_amount"] += r["total_amount"] or Decimal("0")
        by_series[r["series"]] = by_series.get(r["series"], 0) + 1

    return {
        "count": totals["count"],
        "total_taxable_value": str(totals["total_taxable_value"]),
        "total_cgst": str(totals["total_cgst"]),
        "total_sgst": str(totals["total_sgst"]),
        "total_igst": str(totals["total_igst"]),
        "total_tax": str(totals["total_tax"]),
        "total_amount": str(totals["total_amount"]),
        "by_series": by_series,
    }


CSV_COLUMNS = [
    "invoice_number", "invoice_date", "financial_year", "series",
    "supplier_name", "supplier_gstin", "supplier_address", "supplier_state_code",
    "franchisee_id", "franchisee_business_name", "franchisee_gstin",
    "franchisee_address", "franchisee_state", "franchisee_state_code",
    "customer_name", "customer_identifier", "customer_address",
    "place_of_supply_state_code", "is_inter_state",
    "station_name", "station_location", "charger_id_str", "connector_type",
    "energy_consumed_kwh", "tariff_rate_incl_tax",
    "charged_on", "duration_seconds",
    "hsn_sac_code", "gst_rate_percent",
    "energy_taxable_value",
    "gateway_hsn_code", "gateway_charges", "gateway_gst",
    "total_taxable_value",
    "cgst_rate", "cgst_amount", "sgst_rate", "sgst_amount",
    "igst_rate", "igst_amount",
    "total_tax", "total_amount", "amount_in_words",
    "payment_method", "transaction_amount", "refund_amount",
    "transaction_id",
]


def _csv_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return f"{v:f}"  # avoid scientific notation
    return str(v)


@router.get("/api/admin/invoices/export.csv")
async def admin_export_invoices_csv(
    franchisee_id: Optional[int] = None,
    financial_year: Optional[str] = None,
    series: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    place_of_supply_state_code: Optional[str] = None,
    is_inter_state: Optional[bool] = None,
    q: Optional[str] = None,
    _admin: User = Depends(require_admin()),
):
    """Stream the filtered invoice set as a flat CSV for GSTR-1 reconciliation.

    Filename: gst_invoices_<fy_or_all>_<YYYY-MM-DD>.csv. One row per invoice
    with every GSTR-1-relevant column. CAs can pivot/aggregate downstream.
    """
    query = _build_filter_query(
        franchisee_id, financial_year, series, start_date, end_date,
        place_of_supply_state_code, is_inter_state, q,
    )
    query = query.order_by("invoice_date", "id")

    async def _stream():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        # Iterate the queryset; one yield per invoice keeps memory flat.
        async for inv in query:
            row = {col: _csv_value(getattr(inv, col, None)) for col in CSV_COLUMNS}
            writer.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    fy_part = financial_year.replace("-", "") if financial_year else "all"
    today = datetime.utcnow().strftime("%Y-%m-%d")
    filename = f"gst_invoices_{fy_part}_{today}.csv"
    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/admin/invoices/{invoice_id}/pdf")
async def admin_download_invoice_pdf(
    invoice_id: int,
    _admin: User = Depends(require_admin()),
):
    """Download invoice PDF (admin)."""
    return await serve_invoice_pdf(invoice_id)


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
    return await serve_invoice_pdf(invoice_id)


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
    return await serve_invoice_pdf(invoice.id)


# ─── Helpers ─────────────────────────────────────────────────────────

def _invoice_to_dict(inv: GSTInvoice) -> dict:
    """Full GST-filing projection. Decimals stringified for JSON safety."""
    def _d(v):
        return str(v) if v is not None else None
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_number,
        "series": inv.series,
        "financial_year": inv.financial_year,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "supplier_name": inv.supplier_name,
        "supplier_gstin": inv.supplier_gstin,
        "supplier_address": inv.supplier_address,
        "supplier_state_code": inv.supplier_state_code,
        # Substore (Razorpay disclosure) — NULL for VoltLync-owned stations
        "franchisee_business_name": inv.franchisee_business_name,
        "franchisee_gstin": inv.franchisee_gstin,
        "franchisee_address": inv.franchisee_address,
        "franchisee_state": inv.franchisee_state,
        "franchisee_state_code": inv.franchisee_state_code,
        "customer_name": inv.customer_name,
        "customer_identifier": inv.customer_identifier,
        "customer_address": inv.customer_address,
        "place_of_supply_state_code": inv.place_of_supply_state_code,
        "is_inter_state": inv.is_inter_state,
        "station_name": inv.station_name,
        "station_location": inv.station_location,
        "charger_id_str": inv.charger_id_str,
        "connector_type": inv.connector_type,
        "energy_consumed_kwh": inv.energy_consumed_kwh,
        "tariff_rate_incl_tax": _d(inv.tariff_rate_incl_tax),
        "charged_on": inv.charged_on.isoformat() if inv.charged_on else None,
        "duration_seconds": inv.duration_seconds,
        "hsn_sac_code": inv.hsn_sac_code,
        "gst_rate_percent": _d(inv.gst_rate_percent),
        "energy_taxable_value": _d(inv.energy_taxable_value),
        "gateway_hsn_code": inv.gateway_hsn_code,
        "gateway_charges": _d(inv.gateway_charges),
        "gateway_gst": _d(inv.gateway_gst),
        "total_taxable_value": _d(inv.total_taxable_value),
        "cgst_rate": _d(inv.cgst_rate),
        "cgst_amount": _d(inv.cgst_amount),
        "sgst_rate": _d(inv.sgst_rate),
        "sgst_amount": _d(inv.sgst_amount),
        "igst_rate": _d(inv.igst_rate),
        "igst_amount": _d(inv.igst_amount),
        "total_tax": _d(inv.total_tax),
        "total_amount": _d(inv.total_amount),
        "amount_in_words": inv.amount_in_words,
        "payment_method": inv.payment_method,
        "transaction_amount": _d(inv.transaction_amount),
        "refund_amount": _d(inv.refund_amount),
        "transaction_id": inv.transaction_id,
        "franchisee_id": inv.franchisee_id,
        "created_at": inv.created_at.isoformat(),
    }


async def serve_invoice_pdf(invoice_id: int):
    """Lazy S3 upload + presigned-URL redirect, with inline fallback.

    Happy path: generate PDF on first request, upload to S3, persist the key
    on `pdf_url`, redirect to a presigned URL. Subsequent requests: redirect
    immediately.

    Fallback: if S3 isn't configured or any S3 call fails (transient outage,
    IAM misconfiguration, bucket missing), stream the freshly-generated PDF
    inline so the admin/franchisee can still download. Logs the failure so
    ops sees it and can fix S3 without 500-ing the API.
    """
    invoice = await GSTInvoice.filter(id=invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Already uploaded — redirect to presigned URL. Catch S3 failures so a
    # transient outage doesn't break the download (regenerate inline instead).
    if invoice.pdf_url:
        try:
            presigned = s3_service.generate_presigned_url(invoice.pdf_url)
            MetricsCollector.increment_counter("Custom/Invoice/PdfDownload/Cached")
            return RedirectResponse(url=presigned, status_code=302)
        except Exception as e:
            logger.warning(
                "S3 presign failed for invoice %s (key=%s); falling back to "
                "inline streaming. Error: %s",
                invoice.id, invoice.pdf_url, e,
            )
            MetricsCollector.increment_counter("Custom/Invoice/PdfDownload/InlineFallback")
            return await _stream_pdf_inline(invoice)

    # Not uploaded yet — generate, try to upload, then either redirect or
    # stream inline if S3 is unavailable.
    pdf_gen_start = time.perf_counter()
    pdf_bytes = await asyncio.to_thread(InvoiceService.generate_pdf, invoice)
    MetricsCollector.record_metric(
        "Custom/Invoice/PdfGeneration/DurationMs",
        (time.perf_counter() - pdf_gen_start) * 1000.0,
    )
    try:
        key = await asyncio.to_thread(s3_service.upload_invoice_pdf, invoice, pdf_bytes)
        invoice.pdf_url = key
        await invoice.save(update_fields=["pdf_url"])
        presigned = s3_service.generate_presigned_url(key)
        MetricsCollector.increment_counter("Custom/S3/InvoiceUpload/Success")
        return RedirectResponse(url=presigned, status_code=302)
    except Exception as e:
        logger.warning(
            "S3 upload failed for invoice %s; serving PDF inline. Error: %s",
            invoice.id, e,
        )
        MetricsCollector.increment_counter("Custom/S3/InvoiceUpload/Failed")
        MetricsCollector.increment_counter("Custom/Invoice/PdfDownload/InlineFallback")
        return await _stream_pdf_inline(invoice, pdf_bytes=pdf_bytes)


async def _stream_pdf_inline(invoice: GSTInvoice, pdf_bytes: bytes = None):
    """Stream a freshly-generated PDF as the response body. Used as the
    fallback when S3 is unavailable. PDF generation runs in a worker thread
    so the event loop stays responsive."""
    import io
    if pdf_bytes is None:
        pdf_bytes = await asyncio.to_thread(InvoiceService.generate_pdf, invoice)
    safe_number = invoice.invoice_number.replace("/", "_")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="invoice_{safe_number}.pdf"',
        },
    )
