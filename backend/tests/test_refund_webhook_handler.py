"""Direct tests for handle_refund_event in routers/webhooks.

Calls the handler directly (bypassing HTTP/signature) the same way
test_settlement_webhook_idempotent_on_replay exercises its handler.
"""
import uuid
from decimal import Decimal

import pytest

from models import (
    Charger, ChargerQRCode, ChargingStation, ChargerStatusEnum,
    QRPayment, QRPaymentStatusEnum, User,
)
from routers.webhooks import handle_refund_event


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def refund_station():
    return await ChargingStation.create(
        name="Refund Test Station",
        latitude=12.0, longitude=77.0, address="X",
    )


@pytest.fixture
async def refund_charger(refund_station):
    return await Charger.create(
        charge_point_string_id=f"refund-{uuid.uuid4().hex[:8]}",
        station_id=refund_station.id,
        name="Refund Test Charger",
        model="M", vendor="V",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.AVAILABLE,
    )


@pytest.fixture
async def refund_qr_code(refund_charger):
    return await ChargerQRCode.create(
        charger=refund_charger,
        razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://razorpay.example/qr/x.png",
        is_active=True,
    )


async def _make_qr_payment(charger, qr_code, *, refund_id: str,
                           speed_processed: str | None = None):
    user = await User.create(
        email=f"r_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    return await QRPayment.create(
        charger=charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        amount_paid=Decimal("50.00"),
        razorpay_refund_id=refund_id,
        razorpay_refund_speed_processed=speed_processed,
        status=QRPaymentStatusEnum.REFUNDED,
    )


async def test_refund_processed_marks_processed_at_and_speed(
    client, refund_charger, refund_qr_code,
):
    refund_id = f"rfnd_{uuid.uuid4().hex[:10]}"
    qrp = await _make_qr_payment(refund_charger, refund_qr_code, refund_id=refund_id)

    await handle_refund_event(
        event_type="refund.processed",
        event_data={"refund": {"entity": {
            "id": refund_id,
            "speed_processed": "instant",
        }}},
    )
    await qrp.refresh_from_db()
    assert qrp.refund_processed_at is not None
    assert qrp.razorpay_refund_speed_processed == "instant"
    assert qrp.refund_failure_reason is None


async def test_refund_failed_records_reason(client, refund_charger, refund_qr_code):
    refund_id = f"rfnd_{uuid.uuid4().hex[:10]}"
    qrp = await _make_qr_payment(refund_charger, refund_qr_code, refund_id=refund_id)

    await handle_refund_event(
        event_type="refund.failed",
        event_data={"refund": {"entity": {
            "id": refund_id,
            "error": {"description": "Bank rejected transfer"},
        }}},
    )
    await qrp.refresh_from_db()
    assert qrp.refund_failure_reason == "Bank rejected transfer"


async def test_refund_speed_changed_updates_speed(
    client, refund_charger, refund_qr_code,
):
    """Razorpay silently downgraded instant → normal. We must reflect that so
    the customer-facing ETA stays honest (ADR 0005)."""
    refund_id = f"rfnd_{uuid.uuid4().hex[:10]}"
    qrp = await _make_qr_payment(
        refund_charger, refund_qr_code, refund_id=refund_id, speed_processed="instant",
    )

    await handle_refund_event(
        event_type="refund.speed_changed",
        event_data={"refund": {"entity": {
            "id": refund_id,
            "speed_processed": "normal",
        }}},
    )
    await qrp.refresh_from_db()
    assert qrp.razorpay_refund_speed_processed == "normal"


async def test_refund_speed_changed_missing_speed_is_noop(
    client, refund_charger, refund_qr_code,
):
    refund_id = f"rfnd_{uuid.uuid4().hex[:10]}"
    qrp = await _make_qr_payment(
        refund_charger, refund_qr_code, refund_id=refund_id, speed_processed="instant",
    )

    await handle_refund_event(
        event_type="refund.speed_changed",
        event_data={"refund": {"entity": {"id": refund_id}}},
    )
    await qrp.refresh_from_db()
    assert qrp.razorpay_refund_speed_processed == "instant"


async def test_refund_event_for_unknown_refund_id_is_noop(client, refund_charger):
    # No QRPayment carries this refund_id. Handler should log and return.
    await handle_refund_event(
        event_type="refund.processed",
        event_data={"refund": {"entity": {
            "id": "rfnd_nonexistent",
            "speed_processed": "instant",
        }}},
    )
