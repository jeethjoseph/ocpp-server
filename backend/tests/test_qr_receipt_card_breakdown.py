"""Regression: the public QR receipt card breakdown matches the GST invoice.

Per bill-card-consistency issue 01, the customer card must show the same
reconciled numbers as the PDF: energy_cost + gateway_fee + gst_amount must equal
amount_paid − refund. Post-ADR 0026 the gateway line is the ACTUAL Razorpay fee
(razorpay_commission + razorpay_gst) — the same value the invoice carries — not a
synthetic split of amount_paid. The raw ops fields (platform_fee / fee_source)
are still never surfaced to the customer.
"""
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models import (
    Charger, ChargerQRCode, ChargingStation, ChargerStatusEnum, Connector,
    QRPayment, QRPaymentStatusEnum, Transaction, TransactionStatusEnum, User,
)
from routers.public_qr_transactions import _customer_breakdown

ENDPOINT = "/api/public/qr-transactions"


def test_breakdown_from_invoice_reconciles_and_hides_real_fee():
    invoice = SimpleNamespace(
        energy_consumed_kwh=Decimal("3.065"),
        energy_taxable_value=Decimal("63.64"),
        gateway_charges=Decimal("1.69"), gateway_gst=Decimal("0.31"),
        is_inter_state=False,
        sgst_rate=Decimal("9.00"), sgst_amount=Decimal("5.88"),
        cgst_rate=Decimal("9.00"), cgst_amount=Decimal("5.88"),
        igst_rate=None, igst_amount=None,
        total_tax=Decimal("11.76"), total_amount=Decimal("77.09"),
        transaction_amount=Decimal("100.00"),
        hsn_sac_code="996749", gateway_hsn_code="997158",
    )
    payment = SimpleNamespace(amount_paid=Decimal("100.00"))
    b = _customer_breakdown(payment, txn=None, invoice=invoice)
    # Backward-compat flat fields kept.
    assert b["energy_cost"] == "63.64"
    assert b["gateway_fee"] == "1.69"
    # Itemised tax-inclusive line totals (ADR 0024), summing to bill_total.
    assert b["line_items"] == [
        {"label": "Energy", "amount": "75.10"},
        {"label": "Gateway charges", "amount": "1.99"},
    ]
    assert b["bill_total"] == "77.09"
    assert sum(Decimal(i["amount"]) for i in b["line_items"]) == Decimal(b["bill_total"])
    assert "platform_fee" not in b and "razorpay_commission" not in b


def test_breakdown_actual_fee_fallback_reconciles_without_invoice():
    txn = SimpleNamespace(
        energy_consumed_kwh=Decimal("3.065"),
        energy_charge=Decimal("63.64"),
        gst_amount=Decimal("11.46"),
    )
    # No invoice yet: the fallback reads the ACTUAL fee off the payment row
    # (ADR 0026) — commission 0.99 + gst 0.18 = 1.17 gateway.
    payment = SimpleNamespace(
        amount_paid=Decimal("100.00"),
        razorpay_commission=Decimal("0.99"),
        razorpay_gst=Decimal("0.18"),
    )
    b = _customer_breakdown(payment, txn=txn, invoice=None)
    assert b["gateway_fee"] == "0.99"
    assert b["gst_amount"] == "11.64"  # 11.46 energy GST + 0.18 gateway GST
    total = Decimal(b["energy_cost"]) + Decimal(b["gateway_fee"]) + Decimal(b["gst_amount"])
    assert total == Decimal("76.27")
    # Fallback still yields itemised line totals summing to bill_total.
    assert b["line_items"] == [
        {"label": "Energy", "amount": "75.10"},          # 63.64 + 11.46 energy GST
        {"label": "Gateway charges", "amount": "1.17"},  # 0.99 + 0.18 gateway GST
    ]
    assert b["bill_total"] == "76.27"


def test_breakdown_no_billing_returns_nulls():
    txn = SimpleNamespace(energy_consumed_kwh=Decimal("2.0"), energy_charge=None, gst_amount=None)
    b = _customer_breakdown(SimpleNamespace(amount_paid=Decimal("50.00")), txn=txn, invoice=None)
    assert b["energy_cost"] is None and b["gateway_fee"] is None and b["gst_amount"] is None
    assert b["line_items"] == [] and b["bill_total"] is None


@pytest.mark.asyncio
async def test_endpoint_hides_razorpay_fee_and_reconciles(client):
    vpa = "cardtest@okhdfc"
    station = await ChargingStation.create(name="S", latitude=12.0, longitude=77.0, address="x")
    charger = await Charger.create(
        charge_point_string_id=f"ct-{uuid.uuid4().hex[:8]}", station_id=station.id,
        name="C", model="M", vendor="V", serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    await Connector.create(charger_id=charger.id, connector_id=1, connector_type="Type2", max_power_kw=7.4)
    qr = await ChargerQRCode.create(
        charger=charger, razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://x/qr.png", is_active=True,
    )
    user = await User.create(
        email=f"ct_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    txn = await Transaction.create(
        user=user, charger=charger, transaction_status=TransactionStatusEnum.COMPLETED,
        energy_consumed_kwh=Decimal("3.065"), energy_charge=Decimal("63.64"),
        gst_amount=Decimal("11.46"),
    )
    # refund_amount is consistent with the ACTUAL fee (ADR 0026):
    # 100 − energy 63.64 − energy-GST 11.46 − gateway 1.17 = 23.73.
    p = await QRPayment.create(
        charger=charger, charger_qr_code=qr, user=user, transaction=txn,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}", razorpay_qr_code_id=qr.razorpay_qr_code_id,
        amount_paid=Decimal("100.00"), refund_amount=Decimal("23.73"), customer_vpa=vpa,
        status=QRPaymentStatusEnum.REFUNDED,
        platform_fee=Decimal("1.17"), razorpay_commission=Decimal("0.99"),
        razorpay_gst=Decimal("0.18"), fee_source="webhook",
    )
    resp = await client.get(ENDPOINT, params={"vpa": vpa})
    assert resp.status_code == 200
    row = {r["id"]: r for r in resp.json()["data"]}[p.id]

    # The ops-only real Razorpay fee must NOT be exposed to the customer.
    assert "platform_fee" not in row
    assert "razorpay_commission" not in row
    assert "fee_source" not in row
    # Actual gateway fee (commission) shown; card reconciles to net paid.
    assert row["gateway_fee"] == "0.99"
    assert row["gst_amount"] == "11.64"  # 11.46 energy GST + 0.18 gateway GST
    net = Decimal(row["energy_cost"]) + Decimal(row["gateway_fee"]) + Decimal(row["gst_amount"])
    assert net == Decimal(row["amount_paid"]) - Decimal(row["refund_amount"])  # 76.27 == 100 − 23.73
    # Itemised line totals sum to bill_total, which equals amount_paid − refund.
    assert [i["label"] for i in row["line_items"]] == ["Energy", "Gateway charges"]
    assert sum(Decimal(i["amount"]) for i in row["line_items"]) == Decimal(row["bill_total"])
    assert Decimal(row["bill_total"]) == Decimal(row["amount_paid"]) - Decimal(row["refund_amount"])
