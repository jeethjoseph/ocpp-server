"""Unit tests for WalletService GST billing logic + W1 atomicity fix."""
import pytest
from decimal import Decimal

from services.wallet_service import WalletService
from models import Transaction, TransactionStatusEnum, Wallet


# ============================================================================
# Pure unit tests for calculate_billing_amount
# ============================================================================

class TestCalculateBillingAmount:
    """Pure unit tests — no DB. Verifies GST math and rounding."""

    def test_default_18_percent_gst(self):
        energy_charge, gst, total = WalletService.calculate_billing_amount(
            energy_consumed_kwh=10.0,
            rate_per_kwh=Decimal("15.00"),
            gst_percent=Decimal("18.00"),
        )
        assert energy_charge == Decimal("150.00")
        assert gst == Decimal("27.00")
        assert total == Decimal("177.00")

    def test_zero_energy_returns_zeros(self):
        energy_charge, gst, total = WalletService.calculate_billing_amount(
            energy_consumed_kwh=0.0,
            rate_per_kwh=Decimal("15.00"),
            gst_percent=Decimal("18.00"),
        )
        assert energy_charge == Decimal("0.00")
        assert gst == Decimal("0.00")
        assert total == Decimal("0.00")

    def test_negative_energy_returns_zeros(self):
        # Defensive: negative energy treated as zero
        energy_charge, gst, total = WalletService.calculate_billing_amount(
            energy_consumed_kwh=-1.0,
            rate_per_kwh=Decimal("15.00"),
            gst_percent=Decimal("18.00"),
        )
        assert energy_charge == Decimal("0.00")
        assert gst == Decimal("0.00")
        assert total == Decimal("0.00")

    def test_5_percent_gst(self):
        # Lower-bracket GST scenario
        energy_charge, gst, total = WalletService.calculate_billing_amount(
            energy_consumed_kwh=10.0,
            rate_per_kwh=Decimal("12.00"),
            gst_percent=Decimal("5.00"),
        )
        assert energy_charge == Decimal("120.00")
        assert gst == Decimal("6.00")
        assert total == Decimal("126.00")

    def test_28_percent_gst(self):
        # Higher-bracket GST scenario
        energy_charge, gst, total = WalletService.calculate_billing_amount(
            energy_consumed_kwh=10.0,
            rate_per_kwh=Decimal("20.00"),
            gst_percent=Decimal("28.00"),
        )
        assert energy_charge == Decimal("200.00")
        assert gst == Decimal("56.00")
        assert total == Decimal("256.00")

    def test_decimal_rounding_half_up(self):
        # 3.333 kWh × ₹15/kWh = ₹49.995 → rounds up to ₹50.00
        energy_charge, gst, total = WalletService.calculate_billing_amount(
            energy_consumed_kwh=3.333,
            rate_per_kwh=Decimal("15.00"),
            gst_percent=Decimal("18.00"),
        )
        assert energy_charge == Decimal("50.00")
        # 50.00 × 0.18 = 9.00 exactly
        assert gst == Decimal("9.00")
        assert total == Decimal("59.00")

    def test_returns_tuple_of_three(self):
        result = WalletService.calculate_billing_amount(
            energy_consumed_kwh=1.0,
            rate_per_kwh=Decimal("10.00"),
            gst_percent=Decimal("18.00"),
        )
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert all(isinstance(x, Decimal) for x in result)


# ============================================================================
# DB-backed tests for process_transaction_billing W1 atomicity fix
# ============================================================================

class TestProcessTransactionBillingAtomicity:
    """Verifies the W1 fix: billing breakdown must be NULL on BILLING_FAILED."""

    @pytest.mark.asyncio
    async def test_billing_failed_when_no_wallet_leaves_breakdown_null(
        self, client, test_charger, test_user, test_tariff
    ):
        """W1: if wallet doesn't exist, transaction must NOT have populated
        energy_charge/gst_amount/total_billed. Otherwise reports double-count."""
        # No wallet created — billing must fail
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.STOPPED,
            start_meter_kwh=0.0,
            end_meter_kwh=10.0,
            energy_consumed_kwh=10.0,
        )

        success, message, amount = await WalletService.process_transaction_billing(txn.id)

        assert success is False
        assert "Wallet not found" in message

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.BILLING_FAILED
        # The W1 fix: these MUST be None, not populated
        assert refreshed.energy_charge is None, \
            "W1 regression: energy_charge populated despite BILLING_FAILED"
        assert refreshed.gst_amount is None, \
            "W1 regression: gst_amount populated despite BILLING_FAILED"
        assert refreshed.total_billed is None, \
            "W1 regression: total_billed populated despite BILLING_FAILED"

    @pytest.mark.asyncio
    async def test_successful_billing_populates_breakdown(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Happy path: successful billing must populate all three breakdown fields."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.STOPPED,
            start_meter_kwh=0.0,
            end_meter_kwh=10.0,
            energy_consumed_kwh=10.0,
        )

        success, message, amount = await WalletService.process_transaction_billing(txn.id)

        assert success is True
        # 10 kWh × ₹15 = ₹150 + 18% GST ₹27 = ₹177
        assert amount == Decimal("177.00")

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.energy_charge == Decimal("150.00")
        assert refreshed.gst_amount == Decimal("27.00")
        assert refreshed.total_billed == Decimal("177.00")

        # Wallet should be debited by total_billed (not just energy)
        wallet = await Wallet.get(user_id=test_user.id)
        assert wallet.balance == Decimal("500.00") - Decimal("177.00")

    @pytest.mark.asyncio
    async def test_zero_energy_skips_billing_no_breakdown_written(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Zero energy short-circuits before any breakdown is written."""
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.STOPPED,
            start_meter_kwh=10.0,
            end_meter_kwh=10.0,
            energy_consumed_kwh=0.0,
        )

        success, message, amount = await WalletService.process_transaction_billing(txn.id)

        assert success is True
        assert amount == Decimal("0.00")
        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.energy_charge is None
        assert refreshed.gst_amount is None
        assert refreshed.total_billed is None
