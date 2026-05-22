"""Unit tests for services/transaction_finalizer.py."""
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from services.transaction_finalizer import finalize_stopped_transaction
from services.wallet_service import WalletService
from models import Transaction, TransactionStatusEnum, MeterValue, Wallet


@pytest.fixture(autouse=True)
def no_qr_calls():
    """Patch out QRPaymentService calls so finalizer tests don't need a real QRPayment row."""
    with patch("services.qr_payment_service.QRPaymentService.process_qr_session_billing", new=AsyncMock()):
        with patch("services.qr_payment_service.QRPaymentService.handle_charging_failure", new=AsyncMock()):
            yield


class TestFinalizeStoppedTransaction:
    @pytest.mark.asyncio
    async def test_happy_path_with_meter_values(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """RUNNING txn with meter values → STOPPED, billed, breakdown populated."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            start_meter_kwh=0.0,
        )
        await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=10.0,
            measurand="Energy.Active.Import.Register",
        )

        await finalize_stopped_transaction(txn, "TEST_REASON")

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.STOPPED
        assert refreshed.stop_reason == "TEST_REASON"
        assert refreshed.end_time is not None
        assert refreshed.end_meter_kwh == 10.0
        assert refreshed.energy_consumed_kwh == 10.0
        # Billing should have populated breakdown
        assert refreshed.energy_charge == Decimal("150.00")
        assert refreshed.gst_amount == Decimal("27.00")
        assert refreshed.total_billed == Decimal("177.00")
        # Wallet should have been debited (balance derived from the log)
        wallet = await Wallet.get(user_id=test_user.id)
        assert await WalletService.get_balance(wallet.id) == Decimal("500.00") - Decimal("177.00")

    @pytest.mark.asyncio
    async def test_no_meter_values_skips_billing(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """No meter values → energy stays 0 → billing skipped, status STOPPED."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            start_meter_kwh=0.0,
            energy_consumed_kwh=0.0,
        )

        await finalize_stopped_transaction(txn, "NO_METER_TEST")

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.STOPPED
        assert refreshed.stop_reason == "NO_METER_TEST"
        assert refreshed.energy_charge is None
        assert refreshed.gst_amount is None
        # Wallet untouched
        wallet = await Wallet.get(user_id=test_user.id)
        assert await WalletService.get_balance(wallet.id) == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_already_stopped_is_idempotent(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """An already-STOPPED transaction must be a no-op."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.STOPPED,
            stop_reason="ORIGINAL_REASON",
            start_meter_kwh=0.0,
            end_meter_kwh=5.0,
            energy_consumed_kwh=5.0,
        )

        await finalize_stopped_transaction(txn, "DOUBLE_FINALIZE")

        refreshed = await Transaction.get(id=txn.id)
        # stop_reason should NOT have changed
        assert refreshed.stop_reason == "ORIGINAL_REASON"
        # Wallet should NOT have been debited
        wallet = await Wallet.get(user_id=test_user.id)
        assert await WalletService.get_balance(wallet.id) == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_already_billing_failed_is_idempotent(
        self, client, test_charger, test_user, test_tariff
    ):
        """A BILLING_FAILED transaction must not be re-processed."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.BILLING_FAILED,
            start_meter_kwh=0.0,
        )

        # No exception should be raised
        await finalize_stopped_transaction(txn, "RETRY_TEST")

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.BILLING_FAILED

    @pytest.mark.asyncio
    async def test_pops_disconnect_flap_counter(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Finalize must clean up the in-memory flap counter for the txn."""
        from services.disconnect_handler import _disconnect_reset_count
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            start_meter_kwh=0.0,
        )
        _disconnect_reset_count[txn.id] = 2

        await finalize_stopped_transaction(txn, "TEST")

        assert txn.id not in _disconnect_reset_count, \
            "Finalizer did not pop the flap counter for the txn"

    @pytest.mark.asyncio
    async def test_clears_zero_energy_redis_state(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Finalize must call clear_zero_energy_tracking."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            start_meter_kwh=0.0,
        )
        with patch("services.zero_energy_watchdog.clear_zero_energy_tracking", new=AsyncMock()) as mock_clear:
            await finalize_stopped_transaction(txn, "TEST")
            mock_clear.assert_called_once_with(txn.id)
