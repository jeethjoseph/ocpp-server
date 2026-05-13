"""Tests for the GST invoice generation flow after the schema cleanup."""

import os
from decimal import Decimal

import pytest

from models import (
    Charger,
    ChargingStation,
    Connector,
    GSTInvoice,
    QRPayment,
    QRPaymentStatusEnum,
    Tariff,
    Transaction,
    TransactionStatusEnum,
    User,
)
from services import invoice_service as _svc
from services.invoice_service import InvoiceService


@pytest.fixture(autouse=True)
def _voltlync_supplier(monkeypatch):
    """Provide a valid VoltLync GSTIN for every test that doesn't opt out.

    Module-level constants are captured at import time, so env-var tricks
    after import don't take effect — we patch the constants directly.
    """
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "32ABCDE1234F1Z5")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE_CODE", "32")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE", "Kerala")


async def _make_session(
    rate=Decimal("20.00"),
    gst_percent=Decimal("18.00"),
    energy_kwh=1.0,
    station_state_code="32",
    with_qr=False,
    franchisee=None,
):
    """Create a station+charger+transaction+(qr_payment) fixture inline."""
    station = await ChargingStation.create(
        name="Test Station",
        state="Kerala",
        state_code=station_state_code,
        franchisee=franchisee,
    )
    import uuid as _uuid
    charger = await Charger.create(
        charge_point_string_id=f"chg-{_uuid.uuid4().hex[:8]}",
        station=station,
        latest_status="Available",
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    await Tariff.create(
        charger=charger,
        rate_per_kwh=rate,
        gst_percent=gst_percent,
        is_global=False,
        hsn_sac_code="996749",
    )
    user = await User.create(
        email=f"u-{_uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{_uuid.uuid4().int % 1000000000:09d}",
    )

    energy_charge = (Decimal(str(energy_kwh)) * rate).quantize(Decimal("0.01"))
    gst_amount = (energy_charge * gst_percent / Decimal("100")).quantize(Decimal("0.01"))

    txn = await Transaction.create(
        user=user,
        charger=charger,
        energy_consumed_kwh=energy_kwh,
        energy_charge=energy_charge,
        gst_amount=gst_amount,
        gst_rate_percent=gst_percent,
        total_billed=energy_charge + gst_amount,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )

    qr_payment = None
    if with_qr:
        from models import ChargerQRCode
        qr_code = await ChargerQRCode.create(
            charger=charger,
            razorpay_qr_code_id=f"qr_{_uuid.uuid4().hex[:8]}",
            image_url=f"https://r/{_uuid.uuid4().hex[:6]}.png",
            is_active=True,
        )
        qr_payment = await QRPayment.create(
            razorpay_payment_id=f"pay_{_uuid.uuid4().hex[:10]}",
            razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
            charger=charger,
            charger_qr_code=qr_code,
            user=user,
            transaction=txn,
            customer_vpa="testpayer@oksbi",
            amount_paid=Decimal("20.00"),
            energy_cost=energy_charge,
            gst_amount=gst_amount,
            platform_fee=Decimal("0.24"),
            razorpay_commission=Decimal("0.20"),
            razorpay_gst=Decimal("0.04"),
            refund_amount=(
                Decimal("20.00") - energy_charge - gst_amount - Decimal("0.24")
            ),
            status=QRPaymentStatusEnum.REFUNDED,
        )

    return station, charger, txn, user, qr_payment


# ─── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_invoice_uses_stored_taxable_values(client):
    """Energy taxable value should equal txn.energy_charge — no /1.18 reverse-calc."""
    _, _, txn, _, _ = await _make_session(energy_kwh=2.0)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert invoice.energy_taxable_value == txn.energy_charge
    assert invoice.gateway_charges == Decimal("0")
    assert invoice.total_taxable_value == txn.energy_charge
    assert invoice.total_tax == txn.gst_amount
    assert invoice.total_amount == txn.energy_charge + txn.gst_amount
    assert invoice.gst_rate_percent == Decimal("18.00")
    assert invoice.hsn_sac_code == "996749"
    assert invoice.series == "WAL"


@pytest.mark.asyncio
async def test_qr_invoice_uses_vpa_as_customer_name(client):
    """For QR sessions without a customer name, fall back to the VPA."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert invoice.customer_name == qr_payment.customer_vpa
    assert invoice.payment_method == "UPI"
    assert invoice.series == "QR"


@pytest.mark.asyncio
async def test_qr_transaction_amount_is_post_refund(client):
    """transaction_amount on the invoice = amount_paid - refund_amount."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    expected = qr_payment.amount_paid - qr_payment.refund_amount
    assert invoice.transaction_amount == expected


@pytest.mark.asyncio
async def test_qr_invoice_includes_gateway_charges(client):
    """Gateway line = razorpay_commission (taxable) + razorpay_gst (tax)."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice.gateway_charges == qr_payment.razorpay_commission
    assert (
        invoice.total_taxable_value
        == txn.energy_charge + qr_payment.razorpay_commission
    )
    assert invoice.total_tax == txn.gst_amount + qr_payment.razorpay_gst


@pytest.mark.asyncio
async def test_missing_gstin_blocks_issuance(client, monkeypatch):
    """Without a supplier GSTIN, no invoice is issued (CGST Rule 46)."""
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "")

    _, _, txn, _, _ = await _make_session()
    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is None
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
async def test_idempotent_generation(client):
    """Calling generate_invoice twice for the same txn yields the same row."""
    _, _, txn, _, _ = await _make_session()

    first = await InvoiceService.generate_invoice(txn.id)
    second = await InvoiceService.generate_invoice(txn.id)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 1


@pytest.mark.asyncio
async def test_place_of_supply_frozen_on_invoice(client):
    """place_of_supply_state_code captures the station's state at issue time."""
    _, _, txn, _, _ = await _make_session(station_state_code="29")

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice.place_of_supply_state_code == "29"
    # supplier is VoltLync default state_code=32 → inter-state
    assert invoice.is_inter_state is True
    assert invoice.igst_amount == invoice.total_tax
    assert invoice.cgst_amount is None
    assert invoice.sgst_amount is None


@pytest.mark.asyncio
async def test_qr_invoice_kwh_is_billable_not_actual(client):
    """When QR over-consumption was capped, the invoice shows the billable
    kWh (capped), not the actual meter reading. Line-item math reconciles.

    The transaction's energy_consumed_kwh stays as the meter reading; the
    invoice's energy_consumed_kwh is derived from energy_charge / rate so
    that `kWh × rate = total_amount`.
    """
    # rate 20, energy_charge capped at 16.75 (as if process_qr_session_billing
    # capped it). Actual meter reading was 5.0 kWh.
    rate = Decimal("20.00")
    actual_kwh = 5.0
    capped_energy_charge = Decimal("16.75")
    capped_gst = Decimal("3.02")  # 16.75 * 18% rounded

    _, _, txn, _, _ = await _make_session(
        rate=rate, energy_kwh=actual_kwh, with_qr=True
    )
    # Overwrite the txn billing fields to simulate the cap having run.
    await Transaction.filter(id=txn.id).update(
        energy_charge=capped_energy_charge,
        gst_amount=capped_gst,
        total_billed=capped_energy_charge + capped_gst,
    )

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    # billable_kwh = 16.75 / 20 = 0.838 (rounded to 3dp)
    assert invoice.energy_consumed_kwh == pytest.approx(0.838, abs=0.001)
    # Actual meter reading on the transaction is preserved.
    await txn.refresh_from_db()
    assert txn.energy_consumed_kwh == actual_kwh
    # Energy line-item math reconciles: billable_kwh × rate_incl_tax should
    # equal the energy taxable + GST (excluding the separate gateway line).
    energy_incl_tax = capped_energy_charge + capped_gst
    reconciled = Decimal(str(invoice.energy_consumed_kwh)) * invoice.tariff_rate_incl_tax
    assert abs(reconciled - energy_incl_tax) < Decimal("0.05")


@pytest.mark.asyncio
async def test_franchisee_owned_station_invoice_has_voltlync_supplier(client):
    """Sessions at franchisee-owned stations: VoltLync remains the GST supplier.

    The franchisee is captured on `gst_invoice.franchisee_id` for reporting
    (so we can tell which station owner served the session) but never drives
    the supplier columns. VoltLync is the merchant-of-record.
    """
    from datetime import date
    from decimal import Decimal as D
    from models import Franchisee, FranchiseeStatusEnum

    franchisee = await Franchisee.create(
        business_name="Some Franchisee Pvt Ltd",
        contact_name="Alice",
        contact_email="alice@franchisee.test",
        contact_phone="9123456789",
        gstin="29ZZZZZ9999Z1Z5",          # franchisee's own GSTIN
        state="Karnataka",
        state_code="29",                   # would have given different supplier_state_code
        commission_percent=D("20.00"),
        tds_rate_percent=D("10.00"),
        commission_effective_from=date.today(),
        status=FranchiseeStatusEnum.ACTIVE,
    )

    _, _, txn, _, _ = await _make_session(franchisee=franchisee)
    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    # Supplier = VoltLync, NOT the franchisee
    assert invoice.supplier_name == "VOLTLYNC PRIVATE LIMITED"
    assert invoice.supplier_gstin == "32ABCDE1234F1Z5"
    assert invoice.supplier_state_code == "32"
    # But franchisee_id is still on the row for reporting
    assert invoice.franchisee_id == franchisee.id
    # And invoice number has no F{id} segment
    assert invoice.invoice_number.startswith("VL/WAL/")
    assert "/F" not in invoice.invoice_number
