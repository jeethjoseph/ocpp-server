"""Public QR-transactions endpoint: below-minimum refund classification.

A REFUND_FAILED row whose reason is the sub-₹1 Razorpay floor must surface as
`refund_below_minimum: true` so the customer UI renders it as a benign completed
charge rather than a red error. A genuine refund failure stays false.
"""
import uuid
from decimal import Decimal

import pytest

from models import (
    Charger, ChargerQRCode, ChargingStation, ChargerStatusEnum,
    Connector, QRPayment, QRPaymentStatusEnum, User,
)

pytestmark = pytest.mark.asyncio

ENDPOINT = "/api/public/qr-transactions"
VPA = "belowmin_test@okhdfc"


async def _make_payment(status, *, failure_reason=None, refund_amount=None, vpa=VPA):
    station = await ChargingStation.create(name="S", latitude=12.0, longitude=77.0, address="x")
    charger = await Charger.create(
        charge_point_string_id=f"bm-{uuid.uuid4().hex[:8]}", station_id=station.id,
        name="C", model="M", vendor="V", serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    await Connector.create(charger_id=charger.id, connector_id=1, connector_type="Type2", max_power_kw=7.4)
    qr = await ChargerQRCode.create(
        charger=charger, razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://x/qr.png", is_active=True,
    )
    user = await User.create(
        email=f"bm_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    return await QRPayment.create(
        charger=charger, charger_qr_code=qr, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id=qr.razorpay_qr_code_id,
        amount_paid=Decimal("20.00"), customer_vpa=vpa,
        status=status, refund_amount=refund_amount, failure_reason=failure_reason,
    )


async def _get_row(client, payment_id):
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 200
    rows = {r["id"]: r for r in resp.json()["data"]}
    return rows[payment_id]


async def test_below_minimum_refund_failed_flagged_benign(client):
    p = await _make_payment(
        QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason="below_razorpay_minimum", refund_amount=Decimal("0.02"),
    )
    row = await _get_row(client, p.id)
    assert row["status"] == "REFUND_FAILED"
    assert row["refund_below_minimum"] is True


async def test_genuine_refund_failure_not_flagged(client):
    p = await _make_payment(
        QRPaymentStatusEnum.REFUND_FAILED,
        failure_reason="HTTP 500: insufficient balance", refund_amount=Decimal("5.00"),
    )
    row = await _get_row(client, p.id)
    assert row["status"] == "REFUND_FAILED"
    assert row["refund_below_minimum"] is False


async def test_completed_payment_not_flagged(client):
    p = await _make_payment(QRPaymentStatusEnum.COMPLETED)
    row = await _get_row(client, p.id)
    assert row["refund_below_minimum"] is False
