"""Tests for StartTransaction reconcile-then-accept (ADR 0022 / RCA issue 04).

When a charger sends a fresh StartTransaction while an OLD transaction is still
open on that charger, the handler must:
  - finalize a stale/SUSPENDED orphan and ACCEPT the new session (the txn 870/871
    pay-twice fix), never leaving two open transactions;
  - return the SAME transactionId for a network retry of a live start (idempotent);
  - reject a genuinely-live same-charger start with ConcurrentTx.

Reconcile is a module-level function so driving on_start_transaction via a mocked
self still exercises the real logic.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from models import Transaction, TransactionStatusEnum, MeterValue, User

OPEN_STATES = [
    TransactionStatusEnum.STARTED, TransactionStatusEnum.PENDING_START,
    TransactionStatusEnum.RUNNING, TransactionStatusEnum.SUSPENDED,
    TransactionStatusEnum.PENDING_STOP,
]


@pytest.fixture(autouse=True)
def no_qr_calls():
    """Stub QR billing/refund so an orphan finalize stays local (no Razorpay)."""
    with patch("services.qr_payment_service.QRPaymentService.process_qr_session_billing", new=AsyncMock()), \
         patch("services.qr_payment_service.QRPaymentService.handle_charging_failure", new=AsyncMock()):
        yield


@pytest.fixture(autouse=True)
def no_background_tasks():
    """The reconcile now finalizes a superseded orphan OFF the hot path via
    `main.safe_create_task` (so a Razorpay refund can't delay session start), so
    that task must actually RUN for the orphan to reach STOPPED. But the
    fire-and-forget tasks scheduled INSIDE the finalizer (audit/metrics/cleanup,
    `services.transaction_finalizer.safe_create_task`) are neutralized so they
    don't outlive the test loop."""
    import asyncio

    def run_task(coro, *a, **k):
        return asyncio.ensure_future(coro)

    def kill_task(coro, *a, **k):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    with patch("main.safe_create_task", side_effect=run_task), \
         patch("services.transaction_finalizer.safe_create_task", side_effect=kill_task):
        yield


async def _make_user_with_rfid():
    rfid = f"rfid-{uuid.uuid4().hex[:8]}"
    user = await User.create(
        email=f"{uuid.uuid4().hex[:8]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 10**9:09d}",
        rfid_card_id=rfid,
    )
    return user, rfid


async def _start(charge_point_string_id, id_tag, meter_start=0):
    from main import ChargePoint
    fake = MagicMock(spec=ChargePoint)
    fake.id = charge_point_string_id
    return await ChargePoint.on_start_transaction(
        fake, connector_id=1, id_tag=id_tag, meter_start=meter_start,
        timestamp="2026-07-06T10:00:00Z",
    )


async def _open_count(charger) -> int:
    return await Transaction.filter(
        charger_id=charger.id, transaction_status__in=OPEN_STATES,
    ).count()


async def _backdate_start_time(txn_id: int, when: datetime) -> None:
    await Transaction.filter(id=txn_id).update(start_time=when)


async def _await_status(txn_id: int, status, timeout: float = 2.0):
    """Wait for a transaction to reach `status`. The reconcile finalizes a
    superseded orphan OFF the StartTransaction hot path (safe_create_task), so
    the orphan reaches STOPPED shortly after the response returns, not inline."""
    import asyncio
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        txn = await Transaction.get(id=txn_id)
        if txn.transaction_status == status:
            return txn
        await asyncio.sleep(0.02)
    return await Transaction.get(id=txn_id)


@pytest.mark.asyncio
async def test_suspended_orphan_is_superseded_and_new_accepted(client, test_charger):
    """The txn 870/871 fix: a SUSPENDED orphan is finalized and the new session
    accepted — never two open transactions, no forced re-scan failure."""
    user, rfid = await _make_user_with_rfid()
    orphan = await Transaction.create(
        charger=test_charger, user=user,
        transaction_status=TransactionStatusEnum.SUSPENDED,
        suspended_at=datetime.now(timezone.utc) - timedelta(minutes=40),
        start_meter_kwh=0.0,
    )

    result = await _start(test_charger.charge_point_string_id, rfid, meter_start=5000)

    assert result.id_tag_info["status"] == "Accepted"
    refreshed = await _await_status(orphan.id, TransactionStatusEnum.STOPPED)
    assert refreshed.transaction_status == TransactionStatusEnum.STOPPED
    assert refreshed.stop_reason == "SUPERSEDED_BY_NEW_START"
    assert result.transaction_id != orphan.id
    assert await _open_count(test_charger) == 1  # only the new session


@pytest.mark.asyncio
async def test_stale_running_orphan_is_superseded(client, test_charger):
    """A RUNNING txn whose last activity is ancient (we missed its stop) is a
    stale orphan — finalize + accept, don't ConcurrentTx-reject the paying user."""
    user, rfid = await _make_user_with_rfid()
    stale = await Transaction.create(
        charger=test_charger, user=user,
        transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=0.0,
    )
    await _backdate_start_time(stale.id, datetime.now(timezone.utc) - timedelta(hours=1))

    result = await _start(test_charger.charge_point_string_id, rfid, meter_start=5000)

    assert result.id_tag_info["status"] == "Accepted"
    refreshed = await _await_status(stale.id, TransactionStatusEnum.STOPPED)
    assert refreshed.transaction_status == TransactionStatusEnum.STOPPED
    assert await _open_count(test_charger) == 1


@pytest.mark.asyncio
async def test_live_running_is_rejected_concurrent(client, test_charger):
    """A genuinely-live RUNNING txn (recent start, different meter baseline) →
    ConcurrentTx, and NO second transaction is created."""
    user, rfid = await _make_user_with_rfid()
    live = await Transaction.create(
        charger=test_charger, user=user,
        transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=1.0,  # different baseline → not a retry
    )

    result = await _start(test_charger.charge_point_string_id, rfid, meter_start=9000)

    assert result.id_tag_info["status"] == "ConcurrentTx"
    assert result.transaction_id == 0
    # No new transaction — the live one is the only open txn
    assert await _open_count(test_charger) == 1
    assert (await Transaction.get(id=live.id)).transaction_status == TransactionStatusEnum.RUNNING


@pytest.mark.asyncio
async def test_retry_returns_same_transaction_id(client, test_charger):
    """A network retry of a live start (same meter baseline, very recent) is
    idempotent — returns the existing transactionId, creates no duplicate."""
    user, rfid = await _make_user_with_rfid()
    live = await Transaction.create(
        charger=test_charger, user=user,
        transaction_status=TransactionStatusEnum.RUNNING,
        start_meter_kwh=0.0,  # matches incoming meter_start=0
    )

    result = await _start(test_charger.charge_point_string_id, rfid, meter_start=0)

    assert result.id_tag_info["status"] == "Accepted"
    assert result.transaction_id == live.id  # same txn, not a new one
    assert await _open_count(test_charger) == 1


@pytest.mark.asyncio
async def test_no_existing_open_txn_creates_normally(client, test_charger):
    """Baseline: with no open transaction, StartTransaction behaves as before."""
    user, rfid = await _make_user_with_rfid()

    result = await _start(test_charger.charge_point_string_id, rfid, meter_start=0)

    assert result.id_tag_info["status"] == "Accepted"
    assert result.transaction_id > 0
    assert await _open_count(test_charger) == 1
