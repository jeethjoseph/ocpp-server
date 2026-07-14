"""Characterization: disconnect-finalize refunds reconcile against the LAST
pre-disconnect meter reading, not against energy delivered during the outage.

This is a LATENT vulnerability, not an active bug. If a charger were to keep its
contactor closed and keep delivering energy while the OCPP WebSocket is down,
these finalize paths would refund against a stale (too-low) meter reading and
under-charge — up to a full refund when no frame survived the drop.

Verified 2026-07-06 (RCA, ADR 0022): NO deployed VoltLync charger does this.
A fleet-wide cumulative-odometer sweep over every disconnect-finalized session
(11 sessions, 6 chargers, 3.3+7.4 kW) showed the meter never advanced during a
blackout — every unit opens the contactor on WS loss, so every observed refund
was correct. These tests therefore LOCK IN current behavior as a tripwire: if
someone adds energy reconciliation to the finalize path (the deferred fix in
ADR 0022's scope note), or if a future firmware holds the contactor closed,
these assertions change and force a deliberate decision.

The `GROUND_TRUTH_DELIVERED_KWH` below is the hypothetical "car kept charging"
value the system cannot see; the assertions show the refund ignores it.
"""
import uuid
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from models import (
    User, Charger, ChargingStation, Connector, ChargerQRCode, QRPayment,
    QRPaymentStatusEnum, ChargerStatusEnum, Transaction, TransactionStatusEnum,
    MeterValue,
)
from services.transaction_finalizer import finalize_stopped_transaction

# The car actually received this much energy while the socket was down.
GROUND_TRUTH_DELIVERED_KWH = Decimal("6.000")
AMOUNT_PAID = Decimal("27.50")


async def _make_qr_session(last_reading_kwh):
    """Build a SUSPENDED (post-disconnect) QR session whose only persisted meter
    reading is `last_reading_kwh` — the value seen just before the WS dropped.
    Pass None to model 'no meter frame survived the drop'."""
    station = await ChargingStation.create(
        name="Repro Station", latitude=12.0, longitude=77.0, address="x")
    charger = await Charger.create(
        charge_point_string_id=f"repro-{uuid.uuid4().hex[:8]}",
        station_id=station.id, name="Repro", model="m", vendor="v",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.CHARGING)
    await Connector.create(charger_id=charger.id, connector_id=1,
                           connector_type="Type2", max_power_kw=7.4)
    qr_code = await ChargerQRCode.create(
        charger=charger, razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://x/y.png", is_active=True)
    user = await User.create(
        email=f"repro_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}")
    txn = await Transaction.create(
        charger=charger, user=user,
        transaction_status=TransactionStatusEnum.SUSPENDED,  # after disconnect
        start_meter_kwh=Decimal("0.000"))
    if last_reading_kwh is not None:
        await MeterValue.create(
            transaction=txn, charger=charger,
            reading_kwh=Decimal(str(last_reading_kwh)),
            measurand="Energy.Active.Import.Register")
    qr_payment = await QRPayment.create(
        charger=charger, charger_qr_code=qr_code, user=user, transaction=txn,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        amount_paid=AMOUNT_PAID, status=QRPaymentStatusEnum.CHARGING,
        platform_fee=Decimal("0.52"), fee_source="webhook")
    return txn, qr_payment


def _razorpay_mock():
    m = MagicMock()
    for name in ("refund_payment", "find_refund_for_payment", "fetch_payment",
                 "fetch_payment_fees", "fetch_order", "create_transfer"):
        setattr(m, name, AsyncMock())
    m.refund_payment.return_value = {"id": "rfnd_REPRO"}
    m.fetch_payment_fees.return_value = (Decimal("0.52"), Decimal("0.08"))
    return m


async def _finalize_disconnect(txn):
    """Run the disconnect-timer finalize with external I/O stubbed out."""
    with patch("services.qr_payment_service.razorpay_service", _razorpay_mock()) as rp, \
         patch("services.qr_payment_service.redis_manager") as qr_redis, \
         patch("services.franchisee_settlement_service.FranchiseeSettlementService.process_settlement", new=AsyncMock()), \
         patch("services.invoice_service.InvoiceService.generate_invoice", new=AsyncMock()):
        qr_redis.delete_qr_session = AsyncMock()
        await finalize_stopped_transaction(txn, "DISCONNECT_TIMEOUT")
        return rp


@pytest.mark.asyncio
async def test_repro_no_surviving_meter_frame_gives_free_charge(client):
    """WS dropped before any meter frame persisted → energy reads 0 → full
    refund of amount_paid. Would be a free charge IF the car kept charging
    during the outage (no deployed charger does — see module docstring)."""
    txn, qr_payment = await _make_qr_session(last_reading_kwh=None)

    rp = await _finalize_disconnect(txn)

    await qr_payment.refresh_from_db()
    # The bug: entire amount refunded despite real energy delivery.
    rp.refund_payment.assert_called_once()
    assert rp.refund_payment.call_args.kwargs["amount"] == AMOUNT_PAID
    assert qr_payment.refund_amount == AMOUNT_PAID
    assert qr_payment.status == QRPaymentStatusEnum.REFUNDED
    # Ground truth the system ignored:
    assert GROUND_TRUTH_DELIVERED_KWH > 0


@pytest.mark.asyncio
async def test_repro_stale_reading_under_bills(client):
    """The 0.37 kWh from the screenshot (txn 870) is the last pre-disconnect
    reading. Finalize reconciles the refund against that STALE value — so if the
    car had kept charging, nearly the whole payment would still be refunded.

    Note the branch: finalize marks the txn STOPPED (not FAILED), so the
    de-minimis fault-refund band (status==FAILED and 0<energy<0.5) does NOT
    fire. Instead the normal partial-refund formula runs against 0.37 kWh:
      refund = paid - energy_cost(0.37) - gst - gateway_fee.
    With no tariff wired here energy_cost=0, and the gateway is the ACTUAL fee
    (₹0.52, ADR 0026), so refund = 27.50 - 0.52 = 26.98 — a near-total refund
    for a full physical charge."""
    txn, qr_payment = await _make_qr_session(last_reading_kwh="0.370")

    rp = await _finalize_disconnect(txn)

    refreshed = await Transaction.get(id=txn.id)
    # Finalize reconciled against the STALE 0.37 reading, not the 6 kWh delivered.
    assert refreshed.energy_consumed_kwh == Decimal("0.370")
    await qr_payment.refresh_from_db()
    rp.refund_payment.assert_called_once()
    # Near-total refund driven entirely by the stale pre-disconnect reading.
    assert qr_payment.refund_amount == Decimal("26.98")
    assert qr_payment.refund_amount > AMOUNT_PAID * Decimal("0.9")
