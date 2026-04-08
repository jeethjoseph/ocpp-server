"""Unit tests for zero_energy_watchdog state machine."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from services import zero_energy_watchdog
from services.zero_energy_watchdog import (
    check_zero_energy,
    ZERO_ENERGY_GRACE_PERIOD_SECONDS,
    ZERO_ENERGY_TIMEOUT_SECONDS,
)


@pytest.fixture
def mock_redis():
    """Mock the redis_manager calls used by the watchdog."""
    state_store = {}

    async def fake_get(transaction_id):
        return state_store.get(transaction_id)

    async def fake_set(transaction_id, data, ttl=7200):
        state_store[transaction_id] = data
        return True

    async def fake_delete(transaction_id):
        state_store.pop(transaction_id, None)
        return True

    with patch.object(zero_energy_watchdog, "redis_manager") as mock_rm:
        mock_rm.get_zero_energy_state = AsyncMock(side_effect=fake_get)
        mock_rm.set_zero_energy_state = AsyncMock(side_effect=fake_set)
        mock_rm.delete_zero_energy_state = AsyncMock(side_effect=fake_delete)
        yield mock_rm, state_store


class TestGracePeriod:
    @pytest.mark.asyncio
    async def test_skips_check_during_grace_period(self, mock_redis):
        mock_rm, store = mock_redis
        # Transaction started 10 seconds ago — within 60s grace
        start_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        await check_zero_energy(transaction_id=1, reading_kwh=5.0, transaction_start_time=start_time)
        # No state should be written
        assert 1 not in store
        mock_rm.set_zero_energy_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_check_after_grace_writes_state(self, mock_redis):
        mock_rm, store = mock_redis
        # Started long enough ago to be past grace period
        start_time = datetime.now(timezone.utc) - timedelta(seconds=ZERO_ENERGY_GRACE_PERIOD_SECONDS + 30)
        await check_zero_energy(transaction_id=2, reading_kwh=5.0, transaction_start_time=start_time)
        assert 2 in store
        assert store[2]["last_advancing_kwh"] == 5.0
        assert store[2]["previous_kwh"] == 5.0


class TestEnergyAdvancing:
    @pytest.mark.asyncio
    async def test_advancing_energy_resets_stall_clock(self, mock_redis):
        mock_rm, store = mock_redis
        start_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        # First check seeds the state
        await check_zero_energy(transaction_id=3, reading_kwh=5.0, transaction_start_time=start_time)
        original_at = store[3]["last_advancing_at"]
        # Energy advances
        await check_zero_energy(transaction_id=3, reading_kwh=5.5, transaction_start_time=start_time)
        assert store[3]["last_advancing_kwh"] == 5.5
        assert store[3]["previous_kwh"] == 5.5
        # last_advancing_at should be updated to a newer timestamp
        assert store[3]["last_advancing_at"] >= original_at

    @pytest.mark.asyncio
    async def test_energy_progress_zeros_disconnect_flap_counter(self, mock_redis):
        """W5 hook: when energy advances, the disconnect flap counter is popped."""
        from services.disconnect_handler import _disconnect_reset_count
        _disconnect_reset_count[42] = 2

        mock_rm, store = mock_redis
        start_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        # First check seeds state
        await check_zero_energy(transaction_id=42, reading_kwh=5.0, transaction_start_time=start_time)
        # Then energy advances — should pop the counter
        await check_zero_energy(transaction_id=42, reading_kwh=5.5, transaction_start_time=start_time)
        assert 42 not in _disconnect_reset_count, \
            "W5 regression: energy progress did not zero the flap counter"


class TestStalledEnergy:
    @pytest.mark.asyncio
    async def test_stalled_below_timeout_does_not_trigger_stop(self, mock_redis):
        mock_rm, store = mock_redis
        start_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        # Seed with a recent advancing timestamp (within timeout window)
        store[5] = {
            "last_advancing_kwh": 5.0,
            "last_advancing_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
            "previous_kwh": 5.0,
        }
        # Same reading as previous_kwh — no progress
        await check_zero_energy(transaction_id=5, reading_kwh=5.0, transaction_start_time=start_time)
        mock_rm.delete_zero_energy_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_stalled_above_timeout_triggers_cleanup_and_stop(self, mock_redis):
        mock_rm, store = mock_redis
        start_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        # Seed with a stale advancing timestamp (well past timeout)
        stale_ts = datetime.now(timezone.utc) - timedelta(seconds=ZERO_ENERGY_TIMEOUT_SECONDS + 30)
        store[6] = {
            "last_advancing_kwh": 5.0,
            "last_advancing_at": stale_ts.isoformat(),
            "previous_kwh": 5.0,
        }

        # Mock the Transaction lookup. Return a fake txn object so the code
        # proceeds past the not-found early return into the cleanup branch.
        from models import Transaction
        from unittest.mock import MagicMock
        fake_txn = MagicMock()
        fake_txn.charger.charge_point_string_id = "FAKE_CP"
        mock_qs = MagicMock()
        mock_qs.prefetch_related.return_value = mock_qs
        mock_qs.first = AsyncMock(return_value=fake_txn)
        with patch.object(Transaction, "filter", return_value=mock_qs):
            # Mock the connection_manager.send_ocpp_request used by the stop sender
            with patch("services.zero_energy_watchdog._send_zero_energy_stop", new=AsyncMock()):
                await check_zero_energy(transaction_id=6, reading_kwh=5.0, transaction_start_time=start_time)

        # Cleanup should have fired (delete_zero_energy_state called)
        mock_rm.delete_zero_energy_state.assert_called_once_with(6)


class TestTimezoneHandling:
    @pytest.mark.asyncio
    async def test_naive_start_time_does_not_raise(self, mock_redis):
        """Defensive: a tz-naive transaction_start_time should not crash."""
        # Use a naive datetime — the watchdog should normalize it
        naive_start = datetime.utcnow() - timedelta(seconds=300)
        # Should not raise
        await check_zero_energy(transaction_id=7, reading_kwh=5.0, transaction_start_time=naive_start)
