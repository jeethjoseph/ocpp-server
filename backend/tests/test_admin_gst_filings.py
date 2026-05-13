"""Tests for the admin GST filings endpoints (list, summary, CSV export)."""

import csv
import io
from decimal import Decimal

import pytest

from models import (
    Charger,
    ChargingStation,
    Connector,
    GSTInvoice,
    Transaction,
    TransactionStatusEnum,
    User,
)


async def _make_invoice(
    *,
    invoice_number: str,
    series: str = "WAL",
    financial_year: str = "2026-27",
    place_of_supply: str = "32",
    is_inter_state: bool = False,
    energy_taxable: Decimal = Decimal("100.00"),
    total_tax: Decimal = Decimal("18.00"),
    customer_name: str = "Test Customer",
    customer_identifier: str = "test@oksbi",
    franchisee_id=None,
) -> GSTInvoice:
    import uuid as _uuid
    station = await ChargingStation.create(
        name="S",
        state="Kerala",
        state_code="32",
    )
    charger = await Charger.create(
        charge_point_string_id=f"c-{_uuid.uuid4().hex[:8]}",
        station=station,
        latest_status="Available",
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    user = await User.create(
        email=f"u-{_uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{_uuid.uuid4().int % 1000000000:09d}",
    )
    txn = await Transaction.create(
        user=user,
        charger=charger,
        energy_consumed_kwh=1.0,
        energy_charge=energy_taxable,
        gst_amount=total_tax,
        total_billed=energy_taxable + total_tax,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    half_tax = (total_tax / 2).quantize(Decimal("0.01"))
    return await GSTInvoice.create(
        invoice_number=invoice_number,
        series=series,
        financial_year=financial_year,
        transaction=txn,
        franchisee_id=franchisee_id,
        user=user,
        supplier_name="VoltLync",
        supplier_gstin="32ABCDE1234F1Z5",
        supplier_state_code="32",
        customer_name=customer_name,
        customer_identifier=customer_identifier,
        station_name="S",
        place_of_supply_state_code=place_of_supply,
        charger_id_str=charger.charge_point_string_id,
        energy_consumed_kwh=1.0,
        tariff_rate_incl_tax=Decimal("118.00"),
        hsn_sac_code="996749",
        gst_rate_percent=Decimal("18.00"),
        energy_taxable_value=energy_taxable,
        gateway_charges=Decimal("0"),
        total_taxable_value=energy_taxable,
        is_inter_state=is_inter_state,
        cgst_rate=Decimal("9.00") if not is_inter_state else None,
        cgst_amount=half_tax if not is_inter_state else None,
        sgst_rate=Decimal("9.00") if not is_inter_state else None,
        sgst_amount=half_tax if not is_inter_state else None,
        igst_rate=Decimal("18.00") if is_inter_state else None,
        igst_amount=total_tax if is_inter_state else None,
        total_tax=total_tax,
        total_amount=energy_taxable + total_tax,
        payment_method="WALLET",
    )


# ─── List endpoint filters ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_full_projection(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001")
    res = await client_admin.get("/api/admin/invoices")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    row = body["data"][0]
    for col in [
        "supplier_gstin", "place_of_supply_state_code", "hsn_sac_code",
        "gst_rate_percent", "energy_taxable_value", "total_taxable_value",
        "cgst_amount", "sgst_amount", "total_tax", "total_amount",
        "series", "financial_year", "is_inter_state",
    ]:
        assert col in row, f"missing column: {col}"


@pytest.mark.asyncio
async def test_filter_series(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", series="WAL")
    await _make_invoice(invoice_number="VL/QR/202627/00001", series="QR")

    res = await client_admin.get("/api/admin/invoices?series=QR")
    body = res.json()
    assert body["total"] == 1
    assert body["data"][0]["series"] == "QR"


@pytest.mark.asyncio
async def test_filter_financial_year(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", financial_year="2026-27")
    await _make_invoice(invoice_number="VL/WAL/202728/00001", financial_year="2027-28")

    res = await client_admin.get("/api/admin/invoices?financial_year=2027-28")
    body = res.json()
    assert body["total"] == 1
    assert body["data"][0]["financial_year"] == "2027-28"


@pytest.mark.asyncio
async def test_filter_is_inter_state(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", is_inter_state=False)
    await _make_invoice(invoice_number="VL/WAL/202627/00002", is_inter_state=True, place_of_supply="29")

    res = await client_admin.get("/api/admin/invoices?is_inter_state=true")
    assert res.json()["total"] == 1

    res = await client_admin.get("/api/admin/invoices?is_inter_state=false")
    assert res.json()["total"] == 1


@pytest.mark.asyncio
async def test_filter_q_matches_invoice_number_and_customer(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", customer_identifier="alice@oksbi")
    await _make_invoice(invoice_number="VL/WAL/202627/00002", customer_identifier="bob@okhdfc")

    res = await client_admin.get("/api/admin/invoices?q=alice")
    assert res.json()["total"] == 1
    assert "alice" in res.json()["data"][0]["customer_identifier"]

    res = await client_admin.get("/api/admin/invoices?q=00002")
    assert res.json()["total"] == 1


@pytest.mark.asyncio
async def test_invalid_start_date_returns_400(client_admin):
    res = await client_admin.get("/api/admin/invoices?start_date=2026-03-10")
    assert res.status_code == 400
    assert "timezone" in res.json()["detail"]


# ─── Summary endpoint ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_aggregates_match_filtered_set(client_admin):
    await _make_invoice(
        invoice_number="VL/WAL/202627/00001",
        energy_taxable=Decimal("100.00"),
        total_tax=Decimal("18.00"),
    )
    await _make_invoice(
        invoice_number="VL/QR/202627/00001",
        series="QR",
        energy_taxable=Decimal("50.00"),
        total_tax=Decimal("9.00"),
    )

    res = await client_admin.get("/api/admin/invoices/summary")
    body = res.json()
    assert body["count"] == 2
    assert Decimal(body["total_taxable_value"]) == Decimal("150.00")
    assert Decimal(body["total_tax"]) == Decimal("27.00")
    assert Decimal(body["total_amount"]) == Decimal("177.00")
    assert body["by_series"] == {"WAL": 1, "QR": 1}


@pytest.mark.asyncio
async def test_summary_respects_filters(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", series="WAL")
    await _make_invoice(invoice_number="VL/QR/202627/00001", series="QR")

    res = await client_admin.get("/api/admin/invoices/summary?series=QR")
    body = res.json()
    assert body["count"] == 1
    assert body["by_series"] == {"QR": 1}


# ─── CSV export ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csv_export_headers_and_content(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001")
    await _make_invoice(invoice_number="VL/WAL/202627/00002")

    res = await client_admin.get("/api/admin/invoices/export.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    assert ".csv" in res.headers["content-disposition"]

    reader = csv.DictReader(io.StringIO(res.text))
    rows = list(reader)
    assert len(rows) == 2
    # Spot-check columns from the spec
    for col in [
        "invoice_number", "supplier_gstin", "place_of_supply_state_code",
        "cgst_amount", "total_amount", "hsn_sac_code", "gst_rate_percent",
        "series", "financial_year",
        "gateway_charges", "gateway_gst",
    ]:
        assert col in rows[0], f"CSV missing column: {col}"


@pytest.mark.asyncio
async def test_csv_export_respects_filters(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", series="WAL")
    await _make_invoice(invoice_number="VL/QR/202627/00001", series="QR")

    res = await client_admin.get("/api/admin/invoices/export.csv?series=QR")
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert len(rows) == 1
    assert rows[0]["series"] == "QR"


@pytest.mark.asyncio
async def test_csv_filename_contains_fy_when_filtered(client_admin):
    await _make_invoice(invoice_number="VL/WAL/202627/00001", financial_year="2026-27")

    res = await client_admin.get("/api/admin/invoices/export.csv?financial_year=2026-27")
    assert "202627" in res.headers["content-disposition"]


# ─── Authorization ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_admin_blocked(client):
    """`client` has no auth override → all admin endpoints return 401/403."""
    for path in [
        "/api/admin/invoices",
        "/api/admin/invoices/summary",
        "/api/admin/invoices/export.csv",
    ]:
        res = await client.get(path)
        assert res.status_code in (401, 403), f"{path} returned {res.status_code}"
