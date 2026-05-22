"""Tests for the public active-sessions endpoint.

Covers the 4-state classifier (via services.qr_session_state), live-KPI shaping,
cache-miss fallback path, rate limit, and error isolation.
"""
import uuid
from decimal import Decimal

import pytest

from models import (
    Charger, ChargerQRCode, ChargingStation, ChargerStatusEnum,
    Connector, MeterValue, QRPayment, QRPaymentStatusEnum, Tariff,
    Transaction, TransactionStatusEnum, User,
)
from redis_manager import redis_manager


pytestmark = pytest.mark.asyncio


VPA = "active_test@okhdfc"
ENDPOINT = "/api/public/qr-active-sessions"


@pytest.fixture
async def active_station():
    return await ChargingStation.create(
        name="ActSt", latitude=12.0, longitude=77.0, address="x",
    )


@pytest.fixture
async def active_charger(active_station):
    charger = await Charger.create(
        charge_point_string_id=f"act-{uuid.uuid4().hex[:8]}",
        station_id=active_station.id,
        name="ActCharger", model="M", vendor="V",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.CHARGING,
    )
    await Connector.create(
        charger_id=charger.id, connector_id=1,
        connector_type="Type2", max_power_kw=7.4,
    )
    await Tariff.create(
        charger=charger,
        rate_per_kwh=Decimal("20.00"),
        tariff_per_kwh_all_in=Decimal("24.0816"),
        gst_percent=Decimal("18.00"),
        is_global=False,
    )
    return charger


@pytest.fixture
async def active_qr_code(active_charger):
    return await ChargerQRCode.create(
        charger=active_charger,
        razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://razorpay.example/q.png",
        is_active=True,
    )


async def _user():
    return await User.create(
        email=f"u_{uuid.uuid4().hex[:6]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )


async def _qr_payment(charger, qr_code, *, status: QRPaymentStatusEnum, vpa: str = VPA,
                     amount: Decimal = Decimal("50.00")) -> QRPayment:
    user = await _user()
    return await QRPayment.create(
        charger=charger,
        charger_qr_code=qr_code,
        user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
        amount_paid=amount,
        customer_vpa=vpa,
        status=status,
    )


async def _transaction(charger, user, *, status: TransactionStatusEnum,
                       start_meter: Decimal = Decimal("100.000")) -> Transaction:
    return await Transaction.create(
        user=user,
        charger=charger,
        start_meter_kwh=start_meter,
        transaction_status=status,
    )


# ---------------------------------------------------------------------------
# HTTP / integration tests
# ---------------------------------------------------------------------------

async def test_endpoint_invalid_vpa(client):
    resp = await client.get(ENDPOINT, params={"vpa": "not-a-vpa"})
    assert resp.status_code == 400


async def test_endpoint_no_active_returns_empty(client, active_charger, active_qr_code):
    # COMPLETED payment for this VPA — should not appear.
    await _qr_payment(active_charger, active_qr_code, status=QRPaymentStatusEnum.COMPLETED)
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["data"] == []


async def test_endpoint_waiting_state_carries_stale_threshold(
    client, active_charger, active_qr_code,
):
    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.PAID,
    )
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    entry = body["data"][0]
    assert entry["qr_payment_id"] == payment.id
    assert entry["transaction_id"] is None
    assert entry["sub_state"] == "waiting"
    assert entry["energy_kwh"] is None
    assert entry["spent_so_far"] is None
    assert entry["amount_paid"] == "50.00"
    # New in issue 06: waiting entries carry remaining-time-before-auto-refund.
    assert "stale_threshold_seconds" in entry
    assert isinstance(entry["stale_threshold_seconds"], int)
    assert entry["stale_threshold_seconds"] >= 0


async def test_endpoint_charging_state_with_meter_value(
    client, active_charger, active_qr_code,
):
    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.CHARGING,
    )
    user = await payment.user
    txn = await _transaction(
        active_charger, user, status=TransactionStatusEnum.RUNNING,
    )
    payment.transaction_id = txn.id
    await payment.save()

    # Customer has used 1.500 kWh so far at 20/kWh + 18% GST + ₹1 synthetic fee
    # = 1.5 * 20 = 30, GST = 5.40, + 1.00 = 36.40 spent, refund ≈ 13.60
    await MeterValue.create(
        transaction_id=txn.id,
        reading_kwh=Decimal("101.500"),
        power_kw=7.2,
    )

    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 200
    entry = resp.json()["data"][0]
    assert entry["sub_state"] == "charging"
    assert entry["transaction_id"] == txn.id
    assert entry["energy_kwh"] == "1.500"
    assert entry["spent_so_far"] == "36.40"
    assert entry["refund_if_stopped_now"] == "13.60"
    assert entry["power_kw"] == 7.2
    # Issue 06: budget_remaining dropped — refund_if_stopped_now is the single
    # field for "how much would you get back if you stopped now".
    assert "budget_remaining" not in entry


async def test_endpoint_paused_state(client, active_charger, active_qr_code):
    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.CHARGING,
    )
    user = await payment.user
    txn = await _transaction(
        active_charger, user, status=TransactionStatusEnum.SUSPENDED,
    )
    payment.transaction_id = txn.id
    await payment.save()

    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    entry = resp.json()["data"][0]
    assert entry["sub_state"] == "paused"


async def test_endpoint_stopping_state(client, active_charger, active_qr_code):
    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.CHARGING,
    )
    user = await payment.user
    txn = await _transaction(
        active_charger, user, status=TransactionStatusEnum.PENDING_STOP,
    )
    payment.transaction_id = txn.id
    await payment.save()

    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    entry = resp.json()["data"][0]
    assert entry["sub_state"] == "stopping"


async def test_endpoint_charging_but_txn_stopped_is_excluded(
    client, active_charger, active_qr_code,
):
    """Race window: QRPayment.status=CHARGING but Transaction has already
    transitioned to STOPPED. Customer view treats this as no-active-txn,
    so the QRPayment alone (which is CHARGING-without-active-txn) is excluded.
    """
    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.CHARGING,
    )
    user = await payment.user
    txn = await _transaction(
        active_charger, user, status=TransactionStatusEnum.STOPPED,
    )
    payment.transaction_id = txn.id
    await payment.save()

    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.json()["total"] == 0


async def test_endpoint_multiple_active_sessions(client, active_charger, active_qr_code):
    await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.PAID,
    )
    await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.PAID,
        amount=Decimal("75.00"),
    )
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    body = resp.json()
    assert body["total"] == 2
    assert {e["sub_state"] for e in body["data"]} == {"waiting"}


async def test_endpoint_other_vpa_excluded(client, active_charger, active_qr_code):
    await _qr_payment(
        active_charger, active_qr_code,
        status=QRPaymentStatusEnum.CHARGING,
        vpa="someone_else@okhdfc",
    )
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.json()["total"] == 0


async def test_endpoint_uses_cached_meter_snapshot_without_db_query(
    client, active_charger, active_qr_code,
):
    """When `check_budget_and_auto_stop` has stamped `latest_reading_kwh` /
    `latest_power_kw` into the qr_session cache, the active-sessions endpoint
    must read from the cache and NOT query MeterValue (Option 1 of review
    item #4, 2026-05-22).
    """
    from services.qr_payment_service import QRPaymentService

    # Ensure the async Redis client is initialized — the ASGI lifespan that
    # normally calls `redis_manager.connect()` doesn't fire under
    # AsyncClient(transport=ASGITransport(app)).
    if redis_manager.redis_client is None:
        await redis_manager.connect()

    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.CHARGING,
    )
    user = await payment.user
    txn = await _transaction(
        active_charger, user, status=TransactionStatusEnum.RUNNING,
    )
    payment.transaction_id = txn.id
    await payment.save()

    # Clear any prior session for this txn_id (carry-over from another test).
    await redis_manager.delete_qr_session(txn.id)

    # Simulate one MeterValues frame: this is what main.py's MeterValues
    # handler does after persisting a MeterValue row. The function stamps
    # the latest snapshot into the qr_session Redis cache.
    await QRPaymentService.check_budget_and_auto_stop(
        txn.id, reading_kwh=100.500, power_kw=6.4,
    )

    # Deliberately do NOT create a MeterValue row in the DB — the endpoint
    # must serve from the cache alone. (In production a MeterValue WOULD
    # exist; we're proving the read path doesn't depend on it.)
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 200
    entry = resp.json()["data"][0]
    assert entry["sub_state"] == "charging"
    # 0.500 kWh × 20 = 10, GST = 1.80, + 1.00 synthetic fee = 12.80 spent.
    assert entry["energy_kwh"] == "0.500"
    assert entry["spent_so_far"] == "12.80"
    assert entry["refund_if_stopped_now"] == "37.20"
    assert entry["power_kw"] == 6.4


async def test_endpoint_cache_miss_uses_db_fallback(
    client, active_charger, active_qr_code,
):
    """When the qr_session Redis cache is absent, the endpoint must still
    compute KPIs by reading Tariff + QRPayment from the DB. Verifies the
    fallback path matches what the cache-warm path would produce.
    """
    payment = await _qr_payment(
        active_charger, active_qr_code, status=QRPaymentStatusEnum.CHARGING,
    )
    user = await payment.user
    txn = await _transaction(
        active_charger, user, status=TransactionStatusEnum.RUNNING,
    )
    payment.transaction_id = txn.id
    await payment.save()
    await MeterValue.create(
        transaction_id=txn.id, reading_kwh=Decimal("100.500"), power_kw=5.0,
    )

    # Force cache miss
    await redis_manager.delete_qr_session(txn.id)

    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 200
    entry = resp.json()["data"][0]
    assert entry["sub_state"] == "charging"
    # 0.500 kWh × 20 = 10, GST = 1.80, + 1.00 synthetic fee = 12.80 spent.
    assert entry["energy_kwh"] == "0.500"
    assert entry["spent_so_far"] == "12.80"
    assert entry["refund_if_stopped_now"] == "37.20"


async def test_endpoint_rate_limit_429(client, active_charger, active_qr_code):
    """20 req/60s/IP ceiling matches the history endpoint. The conftest
    autouse fixture flushes the rate-limit keys before each test, so the
    counter starts at zero here. Ensures the async redis client is connected
    — the ASGI lifespan that normally calls `redis_manager.connect()` doesn't
    fire under `AsyncClient(transport=ASGITransport(app))`."""
    if redis_manager.redis_client is None:
        await redis_manager.connect()

    for _ in range(20):
        resp = await client.get(ENDPOINT, params={"vpa": VPA})
        assert resp.status_code == 200, resp.text
    resp = await client.get(ENDPOINT, params={"vpa": VPA})
    assert resp.status_code == 429
