"""Tests for the resume staleness guard.

The guard is a defense-in-depth mechanism that refuses to resume a transaction
whose last known activity is older than MAX_RESUME_GAP_SECONDS, even if the
upstream disconnect handler failed to mark it SUSPENDED in time.

Two layers tested:
1. The pure helper `is_resume_too_stale` (unit tests)
2. The BootNotification per-txn handler `_handle_ongoing_transaction_on_boot`
   which is the most-exercised resume entry point and the one with the
   trickiest branching (Plan agent flagged the IF-branch as high-risk).

The MeterValues and GetLastMeterValue resume points use the same helper
inline; their correctness is verified by the unit tests + code review of
the call sites in main.py.
"""
import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from services import transaction_finalizer
from services.transaction_finalizer import (
    is_resume_too_stale,
    MAX_RESUME_GAP_SECONDS,
)
from services.disconnect_handler import _disconnect_reset_count
from models import Transaction, TransactionStatusEnum, MeterValue


@pytest.fixture(autouse=True)
def clear_flap_counter():
    _disconnect_reset_count.clear()
    yield
    _disconnect_reset_count.clear()


@pytest.fixture(autouse=True)
def no_qr_calls():
    """QR billing/refund hits Razorpay; stub it out so finalize is local-only."""
    with patch("services.qr_payment_service.QRPaymentService.process_qr_session_billing", new=AsyncMock()):
        with patch("services.qr_payment_service.QRPaymentService.handle_charging_failure", new=AsyncMock()):
            yield


@pytest.fixture(autouse=True)
def no_background_tasks():
    """Suppress safe_create_task in both call sites so 300s sleeps don't hang
    the test process. Tests verify state at the moment of action."""
    def fake_create_task(coro):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    with patch("services.transaction_finalizer.safe_create_task", side_effect=fake_create_task):
        with patch("main.safe_create_task", side_effect=fake_create_task):
            yield


async def _set_meter_value_created_at(mv_id: int, when: datetime) -> None:
    """MeterValue.created_at is auto_now_add — override via raw UPDATE."""
    await MeterValue.filter(id=mv_id).update(created_at=when)


async def _set_transaction_start_time(txn_id: int, when: datetime) -> None:
    """Transaction.start_time is auto_now_add — override via raw UPDATE."""
    await Transaction.filter(id=txn_id).update(start_time=when)


# ============================================================================
# Unit tests — is_resume_too_stale helper
# ============================================================================

class TestIsResumeTooStale:
    """Pure helper logic — no OCPP, no main.py."""

    @pytest.mark.asyncio
    async def test_returns_false_for_recent_suspended_at(
        self, client, test_charger, test_user
    ):
        recent = datetime.now(timezone.utc) - timedelta(seconds=60)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=recent,
            start_meter_kwh=0.0,
        )
        is_stale, gap = await is_resume_too_stale(txn)
        assert is_stale is False
        assert 50 < gap < 70

    @pytest.mark.asyncio
    async def test_returns_true_for_old_suspended_at(
        self, client, test_charger, test_user
    ):
        old = datetime.now(timezone.utc) - timedelta(seconds=MAX_RESUME_GAP_SECONDS + 300)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=old,
            start_meter_kwh=0.0,
        )
        is_stale, gap = await is_resume_too_stale(txn)
        assert is_stale is True
        assert gap > MAX_RESUME_GAP_SECONDS

    @pytest.mark.asyncio
    async def test_recent_meter_value_overrides_old_suspended_at(
        self, client, test_charger, test_user
    ):
        """Charger has been ticking meter values even after a stale suspended_at —
        not stale, latest activity wins."""
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=old,
            start_meter_kwh=0.0,
        )
        mv = await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=5.0,
            measurand="Energy.Active.Import.Register",
        )
        # Force the MeterValue to "now - 30s"
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        await _set_meter_value_created_at(mv.id, recent)

        is_stale, gap = await is_resume_too_stale(txn)
        assert is_stale is False
        assert gap < 60

    @pytest.mark.asyncio
    async def test_recent_suspended_at_overrides_old_meter_value(
        self, client, test_charger, test_user
    ):
        """Plan agent's mirror case: old MeterValue but recent suspended_at —
        not stale because suspended_at was just refreshed."""
        recent = datetime.now(timezone.utc) - timedelta(seconds=60)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=recent,
            start_meter_kwh=0.0,
        )
        mv = await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=5.0,
            measurand="Energy.Active.Import.Register",
        )
        ancient = datetime.now(timezone.utc) - timedelta(hours=3)
        await _set_meter_value_created_at(mv.id, ancient)

        is_stale, gap = await is_resume_too_stale(txn)
        assert is_stale is False
        assert gap < 120

    @pytest.mark.asyncio
    async def test_falls_back_to_start_time_when_no_other_signals(
        self, client, test_charger, test_user
    ):
        """No suspended_at, no MeterValues — start_time is the only signal."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        old = datetime.now(timezone.utc) - timedelta(seconds=MAX_RESUME_GAP_SECONDS + 100)
        await _set_transaction_start_time(txn.id, old)
        refreshed = await Transaction.get(id=txn.id)

        is_stale, gap = await is_resume_too_stale(refreshed)
        assert is_stale is True
        assert gap > MAX_RESUME_GAP_SECONDS

    @pytest.mark.asyncio
    async def test_recent_start_time_is_not_stale(
        self, client, test_charger, test_user
    ):
        """Brand-new RUNNING txn with no MeterValues yet → start_time wins → fresh."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        is_stale, gap = await is_resume_too_stale(txn)
        assert is_stale is False
        assert gap is not None and gap < 60

    @pytest.mark.asyncio
    async def test_threshold_is_configurable(
        self, client, test_charger, test_user, monkeypatch
    ):
        """Boundary check: a 200s gap is fresh at 900s threshold but stale at 100s."""
        suspended_at = datetime.now(timezone.utc) - timedelta(seconds=200)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        # Default threshold (900s) — 200s is fresh
        is_stale, _ = await is_resume_too_stale(txn)
        assert is_stale is False

        # Tighten threshold to 100s — 200s is now stale
        monkeypatch.setattr(transaction_finalizer, "MAX_RESUME_GAP_SECONDS", 100)
        is_stale, gap = await is_resume_too_stale(txn)
        assert is_stale is True
        assert gap > 100


# ============================================================================
# Integration tests — _handle_ongoing_transaction_on_boot
# ============================================================================

class TestBootNotificationStalenessGuard:
    """Tests the BootNotification per-txn handler. Calls the unbound method
    against a MagicMock self because the full ChargePoint instantiation
    requires a websocket — the helper only depends on `self.id` and
    `self._suspend_timeout`, both of which are easy to stub."""

    def _make_fake_chargepoint(self, charge_point_string_id: str) -> MagicMock:
        from main import ChargePoint
        fake = MagicMock(spec=ChargePoint)
        fake.id = charge_point_string_id
        fake._suspend_timeout = AsyncMock()
        return fake

    @pytest.mark.asyncio
    async def test_finalizes_stale_running_txn(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Plan agent's high-risk regression: a still-RUNNING txn whose last
        meter value is from 1h ago must be finalized, not suspended+resumed."""
        from main import ChargePoint
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        mv = await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=5.0,
            measurand="Energy.Active.Import.Register",
        )
        ancient = datetime.now(timezone.utc) - timedelta(hours=1)
        await _set_meter_value_created_at(mv.id, ancient)
        await _set_transaction_start_time(txn.id, ancient)

        fake_cp = self._make_fake_chargepoint(test_charger.charge_point_string_id)
        now = datetime.now(timezone.utc)
        refreshed = await Transaction.get(id=txn.id)
        await ChargePoint._handle_ongoing_transaction_on_boot(fake_cp, refreshed, now)

        final = await Transaction.get(id=txn.id)
        assert final.transaction_status == TransactionStatusEnum.STOPPED
        assert final.stop_reason == "STALE_RECONNECT"
        assert final.end_meter_kwh == 5.0
        # No suspend timer should have been scheduled
        fake_cp._suspend_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalizes_stale_already_suspended_txn(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Plan agent's IF-branch catch: a SUSPENDED txn whose suspended_at
        is from 1h ago must be finalized, not have suspended_at refreshed."""
        from main import ChargePoint
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=old,
            start_meter_kwh=0.0,
        )
        mv = await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=5.0,
            measurand="Energy.Active.Import.Register",
        )
        await _set_meter_value_created_at(mv.id, old)
        # Pre-existing flap counter entry from a prior disconnect
        _disconnect_reset_count[txn.id] = 1

        fake_cp = self._make_fake_chargepoint(test_charger.charge_point_string_id)
        now = datetime.now(timezone.utc)
        refreshed = await Transaction.get(id=txn.id)
        await ChargePoint._handle_ongoing_transaction_on_boot(fake_cp, refreshed, now)

        final = await Transaction.get(id=txn.id)
        assert final.transaction_status == TransactionStatusEnum.STOPPED
        assert final.stop_reason == "STALE_RECONNECT"
        # Flap counter cleaned up
        assert txn.id not in _disconnect_reset_count
        # No fresh timer
        fake_cp._suspend_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_suspends_fresh_running_txn_normally(
        self, client, test_charger, test_user
    ):
        """A still-RUNNING txn with recent activity should follow the existing
        ELSE-branch path: SUSPENDED + suspend_timeout scheduled."""
        from main import ChargePoint
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=2.0,
            measurand="Energy.Active.Import.Register",
        )

        fake_cp = self._make_fake_chargepoint(test_charger.charge_point_string_id)
        now = datetime.now(timezone.utc)
        refreshed = await Transaction.get(id=txn.id)
        await ChargePoint._handle_ongoing_transaction_on_boot(fake_cp, refreshed, now)

        final = await Transaction.get(id=txn.id)
        assert final.transaction_status == TransactionStatusEnum.SUSPENDED
        assert final.suspended_at == now
        assert final.stop_reason is None
        # Timer was scheduled
        fake_cp._suspend_timeout.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_suspended_at_on_fresh_already_suspended_txn(
        self, client, test_charger, test_user
    ):
        """A SUSPENDED txn with recent suspended_at should follow the existing
        IF-branch path: suspended_at refreshed, flap counter incremented."""
        from main import ChargePoint
        recent = datetime.now(timezone.utc) - timedelta(seconds=30)
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=recent,
            start_meter_kwh=0.0,
        )
        _disconnect_reset_count[txn.id] = 0

        fake_cp = self._make_fake_chargepoint(test_charger.charge_point_string_id)
        now = datetime.now(timezone.utc)
        refreshed = await Transaction.get(id=txn.id)
        await ChargePoint._handle_ongoing_transaction_on_boot(fake_cp, refreshed, now)

        final = await Transaction.get(id=txn.id)
        assert final.transaction_status == TransactionStatusEnum.SUSPENDED
        assert final.suspended_at == now  # refreshed
        assert _disconnect_reset_count[txn.id] == 1
        fake_cp._suspend_timeout.assert_called_once()
