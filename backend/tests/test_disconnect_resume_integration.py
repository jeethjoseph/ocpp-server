"""End-to-end integration: disconnect → suspend → finalize → bill, all in one test."""
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

from services import disconnect_handler
from services.disconnect_handler import (
    suspend_transactions_on_disconnect,
    _disconnect_reset_count,
)
from services.transaction_finalizer import finalize_stopped_transaction
from models import Transaction, TransactionStatusEnum, MeterValue, Wallet


@pytest.fixture(autouse=True)
def clear_flap_counter():
    _disconnect_reset_count.clear()
    yield
    _disconnect_reset_count.clear()


@pytest.fixture(autouse=True)
def no_qr_calls():
    with patch("services.qr_payment_service.QRPaymentService.process_qr_session_billing", new=AsyncMock()):
        with patch("services.qr_payment_service.QRPaymentService.handle_charging_failure", new=AsyncMock()):
            yield


@pytest.fixture(autouse=True)
def no_background_tasks():
    """Suppress safe_create_task so the 180s timeout sleep doesn't hang the test."""
    def fake_create_task(coro):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    with patch("services.disconnect_handler.safe_create_task", side_effect=fake_create_task):
        yield


class TestDisconnectResumeFlow:
    @pytest.mark.asyncio
    async def test_full_disconnect_to_finalize_flow(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """
        Simulates the complete flow:
        1. Charging session running with meter values mid-charge
        2. Charger disconnects → suspend_transactions_on_disconnect
        3. Verify SUSPENDED state
        4. Disconnect timeout fires → finalize_stopped_transaction
        5. Verify STOPPED + billed + wallet debited
        """
        # Step 1: create RUNNING transaction with mid-charge meter values
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=0.0,
        )
        # Mid-charge meter values — energy delivered = 8 kWh
        for kwh in [2.0, 4.0, 6.0, 8.0]:
            await MeterValue.create(
                transaction=txn,
                charger=test_charger,
                reading_kwh=kwh,
                measurand="Energy.Active.Import.Register",
            )

        # Step 2: charger disconnects
        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)

        # Step 3: verify SUSPENDED state
        suspended = await Transaction.get(id=txn.id)
        assert suspended.transaction_status == TransactionStatusEnum.SUSPENDED
        assert suspended.suspended_at is not None
        # Counter initialized
        assert txn.id in _disconnect_reset_count

        # Step 4: disconnect timeout fires → finalize
        # (in production this happens after a 180s sleep — we trigger directly)
        await finalize_stopped_transaction(suspended, "DISCONNECT_TIMEOUT")

        # Step 5: verify STOPPED + billed
        final = await Transaction.get(id=txn.id)
        assert final.transaction_status == TransactionStatusEnum.STOPPED
        assert final.stop_reason == "DISCONNECT_TIMEOUT"
        assert final.end_meter_kwh == 8.0
        assert final.energy_consumed_kwh == 8.0
        # 8 kWh × ₹15/kWh = ₹120 + 18% GST = ₹141.60
        assert final.energy_charge == Decimal("120.00")
        assert final.gst_amount == Decimal("21.60")
        assert final.total_billed == Decimal("141.60")

        # Wallet debited
        wallet = await Wallet.get(user_id=test_user.id)
        assert wallet.balance == Decimal("500.00") - Decimal("141.60")

        # Counter cleaned up after finalization
        assert txn.id not in _disconnect_reset_count

    @pytest.mark.asyncio
    async def test_disconnect_with_zero_energy_no_billing(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """A disconnect with no energy delivered → STOPPED, no wallet debit."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.RUNNING,
            start_meter_kwh=10.0,
        )
        # Meter values that reflect zero progress (start = end)
        await MeterValue.create(
            transaction=txn,
            charger=test_charger,
            reading_kwh=10.0,
            measurand="Energy.Active.Import.Register",
        )

        await suspend_transactions_on_disconnect(test_charger.charge_point_string_id)
        suspended = await Transaction.get(id=txn.id)
        assert suspended.transaction_status == TransactionStatusEnum.SUSPENDED

        await finalize_stopped_transaction(suspended, "DISCONNECT_TIMEOUT")

        final = await Transaction.get(id=txn.id)
        assert final.transaction_status == TransactionStatusEnum.STOPPED
        assert final.energy_consumed_kwh == 0.0
        # No billing breakdown
        assert final.energy_charge is None
        # Wallet untouched
        wallet = await Wallet.get(user_id=test_user.id)
        assert wallet.balance == Decimal("500.00")
