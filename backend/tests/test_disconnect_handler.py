"""Unit tests for disconnect_handler — CAS guard, flap detection, sweep."""
import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock

from services import disconnect_handler
from services.disconnect_handler import (
    suspend_transactions_on_disconnect,
    sweep_stale_suspended_transactions,
    _disconnect_reset_count,
    MAX_RESETS_WITHOUT_PROGRESS,
)
from models import Transaction, TransactionStatusEnum


@pytest.fixture(autouse=True)
def clear_flap_counter():
    """Reset the in-memory flap counter between tests."""
    _disconnect_reset_count.clear()
    yield
    _disconnect_reset_count.clear()


@pytest.fixture(autouse=True)
def no_background_tasks():
    """Patch safe_create_task to swallow background tasks so 180s timeout
    sleeps don't hang the test process. Tests verify state at suspension
    time, not what happens after the timer fires."""
    def fake_create_task(coro):
        # Close the coroutine immediately to suppress 'coroutine was never
        # awaited' warnings without actually scheduling it
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    with patch("services.disconnect_handler.safe_create_task", side_effect=fake_create_task):
        yield


class TestSuspendTransactionsOnDisconnect:
    """Verifies that disconnect callback suspends only active txns."""

    @pytest.mark.asyncio
    async def test_suspends_running_transaction(self, client, test_charger, test_user):
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)
        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.SUSPENDED
        assert refreshed.suspended_at is not None

    @pytest.mark.asyncio
    async def test_suspends_started_pending_start_pending_stop(
        self, client, test_charger, test_user
    ):
        statuses_in = [
            TransactionStatusEnum.STARTED,
            TransactionStatusEnum.PENDING_START,
            TransactionStatusEnum.PENDING_STOP,
        ]
        txns = []
        for s in statuses_in:
            txns.append(await Transaction.create(
                charger=test_charger,
                user=test_user,
                transaction_status=s,
                start_meter_kwh=0.0,
            ))
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)
        for t in txns:
            refreshed = await Transaction.get(id=t.id)
            assert refreshed.transaction_status == TransactionStatusEnum.SUSPENDED

    @pytest.mark.asyncio
    async def test_does_not_touch_already_stopped(
        self, client, test_charger, test_user
    ):
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.STOPPED,
            start_meter_kwh=0.0,
        )
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)
        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.STOPPED


class TestPathologicalFlapDetection:
    """W5: BootNotification resets count toward MAX_RESETS_WITHOUT_PROGRESS,
    blocked when energy hasn't advanced. Helper simulates the BootNotification
    reset path directly without going through the OCPP layer."""

    async def _simulate_bootnotification_reset(self, txn_id: int, now):
        """Simulate the relevant slice of main.py's BootNotification handler
        for an already-SUSPENDED transaction."""
        from services.disconnect_handler import (
            _disconnect_reset_count, MAX_RESETS_WITHOUT_PROGRESS,
        )
        txn = await Transaction.get(id=txn_id)
        if txn.transaction_status != TransactionStatusEnum.SUSPENDED:
            return False  # nothing to reset
        count = _disconnect_reset_count.get(txn_id, 0)
        if count >= MAX_RESETS_WITHOUT_PROGRESS:
            return False  # blocked
        txn.suspended_at = now
        await txn.save()
        _disconnect_reset_count[txn_id] = count + 1
        return True

    @pytest.mark.asyncio
    async def test_disconnect_initializes_counter_to_zero(
        self, client, test_charger, test_user
    ):
        """First disconnect creates a counter entry at 0 (no resets yet)."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)
        assert _disconnect_reset_count[txn.id] == 0

    @pytest.mark.asyncio
    async def test_three_bootnotification_resets_then_blocked(
        self, client, test_charger, test_user
    ):
        """The 4th BootNotification reset attempt must NOT update suspended_at."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)

        # MAX_RESETS_WITHOUT_PROGRESS BootNotification resets succeed
        for i in range(MAX_RESETS_WITHOUT_PROGRESS):
            now = datetime.now(timezone.utc) + timedelta(seconds=i)
            ok = await self._simulate_bootnotification_reset(txn.id, now)
            assert ok is True, f"Reset {i + 1} should have succeeded"

        # Counter should be at max
        assert _disconnect_reset_count[txn.id] == MAX_RESETS_WITHOUT_PROGRESS
        snapshot_suspended_at = (await Transaction.get(id=txn.id)).suspended_at

        # Sleep a tiny amount so a new `now` would be measurably different
        await asyncio.sleep(0.05)

        # The N+1 reset must be blocked
        too_many_now = datetime.now(timezone.utc)
        ok = await self._simulate_bootnotification_reset(txn.id, too_many_now)
        assert ok is False, "W5 regression: reset past max should have been blocked"

        re_refreshed = await Transaction.get(id=txn.id)
        assert re_refreshed.suspended_at == snapshot_suspended_at, \
            "W5 regression: blocked reset still updated suspended_at"
        assert _disconnect_reset_count[txn.id] == MAX_RESETS_WITHOUT_PROGRESS

    @pytest.mark.asyncio
    async def test_energy_progress_zeros_counter(
        self, client, test_charger, test_user
    ):
        """W5 + zero_energy_watchdog hook: real charging progress must zero
        the flap counter, allowing subsequent BootNotification resets."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)

        # Two BootNotification resets without progress
        for i in range(2):
            now = datetime.now(timezone.utc) + timedelta(seconds=i)
            await self._simulate_bootnotification_reset(txn.id, now)
        assert _disconnect_reset_count[txn.id] == 2

        # Simulate the watchdog seeing energy advance — it pops the counter
        _disconnect_reset_count.pop(txn.id, None)
        assert txn.id not in _disconnect_reset_count

        # Next reset starts fresh
        ok = await self._simulate_bootnotification_reset(
            txn.id, datetime.now(timezone.utc) + timedelta(seconds=10)
        )
        assert ok is True
        assert _disconnect_reset_count[txn.id] == 1


class TestSweepStaleSuspendedTransactions:
    """Startup safety net for orphaned SUSPENDED transactions."""

    @pytest.mark.asyncio
    async def test_sweeps_old_suspended_transaction(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        # Use cutoff well past max_timeout (180 + 300 + 60 = 540s)
        old_suspended_at = datetime.now(timezone.utc) - timedelta(seconds=600)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=old_suspended_at,
            start_meter_kwh=0.0,
        )

        await sweep_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status in (
            TransactionStatusEnum.STOPPED,
            TransactionStatusEnum.BILLING_FAILED,
        )
        assert refreshed.stop_reason == "STALE_SUSPEND_SWEEP"

    @pytest.mark.asyncio
    async def test_does_not_sweep_recent_suspended_transaction(
        self, client, test_charger, test_user
    ):
        recent_suspended_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=recent_suspended_at,
            start_meter_kwh=0.0,
        )

        await sweep_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.SUSPENDED, \
            "Recent suspended txn should NOT be swept"
