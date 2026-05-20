"""Unit tests for zero_energy_watchdog state machine."""
import json
from decimal import Decimal

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


class TestDecimalReadingKwh:
    """Regression guard for the 'Decimal is not JSON serializable' staging
    storm (223 occurrences in the recent log window before this fix).

    The MeterValues parser at main.py constructs `reading_kwh` as a Decimal,
    then hands it to `check_zero_energy`. Before the fix, the resulting
    state dict failed `json.dumps`, the Redis write was never persisted,
    and the watchdog couldn't detect stalled sessions for any transaction
    hitting this path."""

    @pytest.mark.asyncio
    async def test_decimal_reading_kwh_serialises_without_crash(self, mock_redis):
        """A Decimal reading_kwh must flow through to the Redis write."""
        mock_rm, store = mock_redis
        start_time = datetime.now(timezone.utc) - timedelta(
            seconds=ZERO_ENERGY_GRACE_PERIOD_SECONDS + 30
        )

        # Pre-fix behaviour: this raised TypeError inside json.dumps.
        await check_zero_energy(
            transaction_id=42,
            reading_kwh=Decimal("5.123"),
            transaction_start_time=start_time,
        )

        # State was written; the values are JSON-safe floats.
        assert 42 in store
        # Round-trip through json.dumps to prove the payload is serialisable
        # with the stdlib defaults (no `default=` kwarg). If a future change
        # re-introduces a Decimal here this test fails loudly.
        json.dumps(store[42])
        assert isinstance(store[42]["last_advancing_kwh"], float)
        assert isinstance(store[42]["previous_kwh"], float)
        assert store[42]["last_advancing_kwh"] == pytest.approx(5.123)

    @pytest.mark.asyncio
    async def test_decimal_advancing_path_also_safe(self, mock_redis):
        """The 'energy advancing' branch overwrites state — also Decimal-safe."""
        mock_rm, store = mock_redis
        start_time = datetime.now(timezone.utc) - timedelta(
            seconds=ZERO_ENERGY_GRACE_PERIOD_SECONDS + 30
        )

        await check_zero_energy(
            transaction_id=43,
            reading_kwh=Decimal("1.000"),
            transaction_start_time=start_time,
        )
        await check_zero_energy(
            transaction_id=43,
            reading_kwh=Decimal("1.500"),
            transaction_start_time=start_time,
        )

        assert store[43]["last_advancing_kwh"] == pytest.approx(1.5)
        json.dumps(store[43])


class TestRedisManagerDefaultStrDefense:
    """Defensive guard at the redis_manager layer. The primary fix is the
    float() cast at the watchdog entry point; this proves the secondary
    `default=str` belt would catch a regression that bypassed the cast."""

    @pytest.mark.asyncio
    async def test_set_zero_energy_state_accepts_decimal_payload(self):
        from redis_manager import RedisConnectionManager

        rm = RedisConnectionManager()
        captured = {}

        class _FakeClient:
            async def set(self, key, value, ex=None):
                captured["key"] = key
                captured["value"] = value
                captured["ex"] = ex
                return True

        rm.redis_client = _FakeClient()
        ok = await rm.set_zero_energy_state(
            99,
            {"last_advancing_kwh": Decimal("3.142"), "previous_kwh": Decimal("3.000")},
        )
        assert ok is True
        # default=str routes Decimals to their str form rather than crashing.
        round_tripped = json.loads(captured["value"])
        assert round_tripped["last_advancing_kwh"] == "3.142"
        assert round_tripped["previous_kwh"] == "3.000"
