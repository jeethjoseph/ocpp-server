"""The suspend window measures silence, not session age.

ADR 0031 decision 3 / offline-continuity issue 02. One derived clock —
disconnect_handler.last_heard_at / silence_seconds — feeds the suspend timer,
the stale-suspended sweep and the resume staleness guard. No column, no
migration: the clock is the newest of suspended_at, the latest MeterValue
receipt, and the transaction start.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from models import MeterValue, Transaction, TransactionStatusEnum
from services.disconnect_handler import (
    _suspend_timers, arm_suspend_timer, finalize_stale_suspended_transactions,
    hold_until_silent, last_heard_at, silence_seconds,
    stale_suspended_cutoff_seconds_for,
)
from services.transaction_finalizer import is_resume_too_stale

pytestmark = pytest.mark.asyncio


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


async def _suspended(charger, user, suspended_at):
    return await Transaction.create(
        charger=charger, user=user, transaction_status=TransactionStatusEnum.SUSPENDED,
        start_meter_kwh=Decimal("1.000"), suspended_at=suspended_at,
    )


async def _reading(txn, created_at, kwh="2.000"):
    mv = await MeterValue.create(transaction=txn, reading_kwh=Decimal(kwh))
    await MeterValue.filter(id=mv.id).update(created_at=created_at)


@pytest.fixture(autouse=True)
def no_billing():
    with patch("services.transaction_finalizer._process_billing", new=AsyncMock()):
        yield


# ------------------------------------------------------------ the clock --

async def test_last_heard_is_the_newest_of_the_three_signals(client, test_charger, test_user):
    txn = await _suspended(test_charger, test_user, suspended_at=_ago(hours=5))
    assert (await last_heard_at(txn)) == txn.suspended_at

    recent = _ago(minutes=3)
    await _reading(txn, recent)
    heard = await last_heard_at(txn)
    assert abs((heard - recent).total_seconds()) < 1
    assert 170 < (await silence_seconds(txn)) < 190


async def test_silence_is_receipt_time_not_measured_time(client, test_charger, test_user):
    """A replayed frame measured 20h ago but received now proves the charger is alive."""
    txn = await _suspended(test_charger, test_user, suspended_at=_ago(hours=20))
    mv = await MeterValue.create(transaction=txn, reading_kwh=Decimal("2.000"),
                                 measured_at=_ago(hours=20))
    assert (await silence_seconds(txn)) < 5


# ------------------------------------------------------------ the sweep --

async def test_sweep_spares_a_transaction_heard_from_recently(client, test_charger, test_user):
    """suspended_at is far past the window, but a reading arrived a minute ago."""
    cutoff = await stale_suspended_cutoff_seconds_for(
        await _suspended(test_charger, test_user, suspended_at=_ago(seconds=1)))
    txn = await _suspended(test_charger, test_user, suspended_at=_ago(seconds=cutoff + 3600))
    await _reading(txn, _ago(minutes=1))

    await finalize_stale_suspended_transactions("STALE_SUSPEND_SWEEP")

    assert (await Transaction.get(id=txn.id)).transaction_status == TransactionStatusEnum.SUSPENDED


async def test_sweep_still_finalizes_a_fully_silent_transaction(client, test_charger, test_user):
    probe = await _suspended(test_charger, test_user, suspended_at=_ago(seconds=1))
    cutoff = await stale_suspended_cutoff_seconds_for(probe)
    txn = await _suspended(test_charger, test_user, suspended_at=_ago(seconds=cutoff + 3600))
    await _reading(txn, _ago(seconds=cutoff + 3000))

    await finalize_stale_suspended_transactions("STALE_SUSPEND_SWEEP")

    fresh = await Transaction.get(id=txn.id)
    assert fresh.transaction_status == TransactionStatusEnum.STOPPED
    assert fresh.stop_reason == "STALE_SUSPEND_SWEEP"


# ------------------------------------------------------------ the guard --

async def test_resume_guard_reads_the_same_clock(client, test_charger, test_user):
    txn = await _suspended(test_charger, test_user, suspended_at=_ago(days=3))
    stale, gap = await is_resume_too_stale(txn)
    assert stale and gap > 2 * 86400

    await _reading(txn, _ago(seconds=30))
    stale, gap = await is_resume_too_stale(txn)
    assert not stale and gap < 60


# ------------------------------------------------------------ the timer --

async def test_timer_re_arms_when_heard_from_inside_the_window(client, test_charger, test_user):
    """Window 1s. A reading at 0.5s pushes the finalize out to ~1.5s."""
    txn = await _suspended(test_charger, test_user, suspended_at=datetime.now(timezone.utc))
    task = asyncio.create_task(hold_until_silent(txn.id, 1, "DISCONNECT_TIMEOUT"))

    await asyncio.sleep(0.5)
    await _reading(txn, datetime.now(timezone.utc))
    await asyncio.sleep(0.7)   # t≈1.2s: original window elapsed, but silence is only ~0.7s
    assert (await Transaction.get(id=txn.id)).transaction_status == TransactionStatusEnum.SUSPENDED

    await asyncio.wait_for(task, timeout=3)
    fresh = await Transaction.get(id=txn.id)
    assert fresh.transaction_status == TransactionStatusEnum.STOPPED
    assert fresh.stop_reason == "DISCONNECT_TIMEOUT"


async def test_timer_exits_quietly_once_resumed(client, test_charger, test_user):
    txn = await _suspended(test_charger, test_user, suspended_at=datetime.now(timezone.utc))
    task = asyncio.create_task(hold_until_silent(txn.id, 1, "DISCONNECT_TIMEOUT"))
    await Transaction.filter(id=txn.id).update(transaction_status=TransactionStatusEnum.RUNNING)

    await asyncio.wait_for(task, timeout=3)
    assert (await Transaction.get(id=txn.id)).transaction_status == TransactionStatusEnum.RUNNING


async def test_arming_again_replaces_the_previous_timer(client, test_charger, test_user):
    txn = await _suspended(test_charger, test_user, suspended_at=datetime.now(timezone.utc))
    first = arm_suspend_timer(txn.id, 60, "DISCONNECT_TIMEOUT")
    second = arm_suspend_timer(txn.id, 60, "SUSPENDED_TIMEOUT")
    await asyncio.sleep(0)

    assert first.cancelled() or first.done()
    assert _suspend_timers[txn.id] is second
    second.cancel()
    await asyncio.sleep(0)
    assert txn.id not in _suspend_timers


async def test_flap_capped_boot_does_not_move_the_clock(client, test_charger, test_user):
    """Past MAX_RESETS_WITHOUT_PROGRESS a reboot no longer re-stamps suspended_at,
    so last_heard_at — and therefore the timer — is unchanged by it."""
    from unittest.mock import MagicMock
    from main import ChargePoint
    from services.disconnect_handler import _disconnect_reset_count, MAX_RESETS_WITHOUT_PROGRESS

    old = _ago(hours=2)
    txn = await _suspended(test_charger, test_user, suspended_at=old)
    _disconnect_reset_count[txn.id] = MAX_RESETS_WITHOUT_PROGRESS
    cp = MagicMock(spec=ChargePoint)
    cp.id = test_charger.charge_point_string_id
    cp._suspend_timeout = AsyncMock()
    try:
        await ChargePoint._handle_ongoing_transaction_on_boot(cp, txn, datetime.now(timezone.utc))
    finally:
        _disconnect_reset_count.pop(txn.id, None)

    assert (await last_heard_at(await Transaction.get(id=txn.id))) == old
    cp._suspend_timeout.assert_not_called()
