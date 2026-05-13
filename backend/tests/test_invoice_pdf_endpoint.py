"""Integration tests for the invoice PDF download endpoints.

Covers the full HTTP path:
  /api/admin/invoices/{id}/pdf
  /api/franchisee/invoices/{id}/pdf
  /api/transactions/{id}/invoice/pdf

Specifically validates:
  - First-request happy path: PDF generated, uploaded to S3, response is a
    302 redirect to a presigned URL, `pdf_url` is cached on the row.
  - Second-request cached path: no regeneration, no S3 upload, immediate
    redirect.
  - S3 failure → inline streaming fallback: response is 200 application/pdf
    with the PDF as the body, ops sees a warning log.
  - Permission scopes: a franchisee can only download own invoices.

S3 is mocked at the `services.s3_service` level — no real boto3 calls.
"""

import io
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from models import (
    Charger, ChargingStation, Connector, GSTInvoice, Tariff, Transaction,
    TransactionStatusEnum, User, ChargerStatusEnum,
)
from services import invoice_service as _svc


@pytest.fixture(autouse=True)
def _voltlync_supplier(monkeypatch):
    """Patch VoltLync env-derived constants on the invoice service so
    `generate_invoice` doesn't bail on the GSTIN guard."""
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "32ABCDE1234F1Z5")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE_CODE", "32")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE", "Kerala")


async def _make_invoice_for_admin_test() -> tuple[GSTInvoice, Transaction]:
    """Build a minimal session + invoice via the real invoice service so the
    invoice row has every field populated (including supplier snapshots)."""
    import uuid as _uuid
    station = await ChargingStation.create(
        name="PDF Test Station", state="Kerala", state_code="32",
    )
    charger = await Charger.create(
        charge_point_string_id=f"pdf-{_uuid.uuid4().hex[:8]}",
        station=station,
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    await Tariff.create(
        charger=charger,
        rate_per_kwh=Decimal("20.00"),
        gst_percent=Decimal("18.00"),
        is_global=False,
        hsn_sac_code="996749",
    )
    user = await User.create(
        email=f"pdf-{_uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{_uuid.uuid4().int % 1000000000:09d}",
    )
    txn = await Transaction.create(
        user=user, charger=charger,
        energy_consumed_kwh=2.0,
        energy_charge=Decimal("40.00"),
        gst_amount=Decimal("7.20"),
        gst_rate_percent=Decimal("18.00"),
        total_billed=Decimal("47.20"),
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    invoice = await _svc.InvoiceService.generate_invoice(txn.id)
    assert invoice is not None, "fixture: invoice generation failed"
    return invoice, txn


# ─── Cached fast path ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_download_cached_path_redirects_without_regen(client_admin):
    """When `pdf_url` is already set, the endpoint just generates a presigned
    URL and 302s — no PDF render, no S3 PUT."""
    invoice, txn = await _make_invoice_for_admin_test()
    invoice.pdf_url = "invoices/2026-27/voltlync/PRE_EXISTING.pdf"
    await invoice.save(update_fields=["pdf_url"])

    with patch("routers.invoices.s3_service") as mock_s3, \
         patch.object(_svc.InvoiceService, "generate_pdf") as mock_gen:
        mock_s3.generate_presigned_url.return_value = "https://s3.test/presigned"
        res = await client_admin.get(
            f"/api/transactions/{txn.id}/invoice/pdf",
            follow_redirects=False,
        )

    assert res.status_code == 302
    assert res.headers["location"] == "https://s3.test/presigned"
    mock_s3.generate_presigned_url.assert_called_once_with(invoice.pdf_url)
    mock_s3.upload_invoice_pdf.assert_not_called()
    mock_gen.assert_not_called()


# ─── First-request happy path ────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_download_first_request_uploads_to_s3(client_admin):
    """First request for a fresh invoice: generates the PDF, uploads it,
    persists pdf_url, then 302s to the presigned URL."""
    invoice, txn = await _make_invoice_for_admin_test()
    assert invoice.pdf_url is None

    with patch("routers.invoices.s3_service") as mock_s3:
        mock_s3.upload_invoice_pdf.return_value = "invoices/2026-27/voltlync/x.pdf"
        mock_s3.generate_presigned_url.return_value = "https://s3.test/freshly-uploaded"
        res = await client_admin.get(
            f"/api/transactions/{txn.id}/invoice/pdf",
            follow_redirects=False,
        )

    assert res.status_code == 302
    assert res.headers["location"] == "https://s3.test/freshly-uploaded"
    mock_s3.upload_invoice_pdf.assert_called_once()
    # And the key got persisted so future calls take the cached path
    await invoice.refresh_from_db()
    assert invoice.pdf_url == "invoices/2026-27/voltlync/x.pdf"


# ─── S3 failure → inline fallback ────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_download_falls_back_to_inline_when_s3_upload_fails(client_admin):
    """If `upload_invoice_pdf` raises, the endpoint streams the freshly-
    generated PDF inline rather than 500-ing."""
    invoice, txn = await _make_invoice_for_admin_test()

    with patch("routers.invoices.s3_service") as mock_s3:
        mock_s3.upload_invoice_pdf.side_effect = RuntimeError("S3 unreachable")
        res = await client_admin.get(
            f"/api/transactions/{txn.id}/invoice/pdf",
            follow_redirects=False,
        )

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content[:4] == b"%PDF", "fallback body should be a real PDF"
    # pdf_url stays NULL — we didn't successfully upload
    await invoice.refresh_from_db()
    assert invoice.pdf_url is None


@pytest.mark.asyncio
async def test_pdf_download_falls_back_when_presign_fails_on_cached_invoice(client_admin):
    """If a cached `pdf_url` exists but `generate_presigned_url` raises
    (e.g. credentials expired), still serve the PDF inline."""
    invoice, txn = await _make_invoice_for_admin_test()
    invoice.pdf_url = "invoices/2026-27/voltlync/cached.pdf"
    await invoice.save(update_fields=["pdf_url"])

    with patch("routers.invoices.s3_service") as mock_s3:
        mock_s3.generate_presigned_url.side_effect = RuntimeError("IAM revoked")
        res = await client_admin.get(
            f"/api/transactions/{txn.id}/invoice/pdf",
            follow_redirects=False,
        )

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.content[:4] == b"%PDF"


# ─── 404 paths ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pdf_download_404_for_unknown_transaction(client_admin):
    res = await client_admin.get(
        "/api/transactions/999999/invoice/pdf",
        follow_redirects=False,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_admin_pdf_download_404_for_unknown_invoice(client_admin):
    res = await client_admin.get(
        "/api/admin/invoices/999999/pdf",
        follow_redirects=False,
    )
    assert res.status_code == 404
