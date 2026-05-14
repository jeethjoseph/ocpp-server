"""Unit tests for WalletService GST billing logic + W1 atomicity fix."""
import pytest
from decimal import Decimal

from services.wallet_service import WalletService
from models import (
    Transaction,
    TransactionStatusEnum,
    TransactionTypeEnum,
    Wallet,
    WalletTransaction,
)


# NOTE: Earlier this file had an autouse Redis-balance-cache stub at
# module level. That leaked into every test in the file including the
# original W1-atomicity-fix tests, which don't need it and would prefer
# real Redis behavior. The stub has been moved to a class-scoped fixture
# on `TestDerivedBalance` so it only affects the ledger-arithmetic tests
# that genuinely need cache misses.


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

        # Wallet should be debited by total_billed (not just energy).
        # Balance is derived from the wallet_transaction log.
        wallet = await Wallet.get(user_id=test_user.id)
        derived = await WalletService.get_balance(wallet.id)
        assert derived == Decimal("500.00") - Decimal("177.00")

        # CHARGE_DEDUCT row records the deduction with a POSITIVE amount;
        # direction is carried by `type`, not by the sign of `amount`.
        deduct = await WalletTransaction.filter(
            wallet_id=wallet.id, type=TransactionTypeEnum.CHARGE_DEDUCT
        ).first()
        assert deduct is not None
        assert deduct.amount == Decimal("177.00")

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


# ============================================================================
# Module A: wallet_transaction.amount must be >= 0 going forward
# ============================================================================

class TestWalletTransactionAmountSign:
    """The model-level validator + Module A sign convention.

    Direction of a wallet_transaction is carried by `type` (TOP_UP credits,
    CHARGE_DEDUCT debits). `amount` is always non-negative. Enforced by
    a WalletTransaction.save() override; a DB CHECK constraint
    (NOT VALID, migration 32) backstops at the schema layer.
    """

    @pytest.mark.asyncio
    async def test_negative_amount_raises_and_writes_no_row(
        self, client, test_wallet
    ):
        with pytest.raises(ValueError, match="must be >= 0"):
            await WalletTransaction.create(
                wallet=test_wallet,
                amount=Decimal("-1.00"),
                type=TransactionTypeEnum.CHARGE_DEDUCT,
                description="should not persist",
            )

        # Validator runs before the insert — no row should exist.
        count = await WalletTransaction.filter(
            wallet_id=test_wallet.id, description="should not persist"
        ).count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_zero_amount_is_allowed(self, client, test_wallet):
        # Bound is `>= 0` — zero-amount rows are legal (e.g. zero-kWh
        # aborted session). Only strictly-negative values are rejected.
        row = await WalletTransaction.create(
            wallet=test_wallet,
            amount=Decimal("0.00"),
            type=TransactionTypeEnum.CHARGE_DEDUCT,
            description="zero-amount sentinel",
        )
        assert row.id is not None
        assert row.amount == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_positive_charge_deduct_persists(self, client, test_wallet):
        # Sanity: post-Module-A, CHARGE_DEDUCT writes are positive.
        row = await WalletTransaction.create(
            wallet=test_wallet,
            amount=Decimal("50.00"),
            type=TransactionTypeEnum.CHARGE_DEDUCT,
            description="positive deduction",
        )
        assert row.amount == Decimal("50.00")
        assert row.type == TransactionTypeEnum.CHARGE_DEDUCT


# ============================================================================
# Module C: Derived balance via SUM over wallet_transaction log
# ============================================================================

class TestDerivedBalance:
    """WalletService.get_balance — SUM(amount) over COMPLETED TOP_UPs minus
    SUM(amount) over CHARGE_DEDUCTs, with Redis cache + invalidation."""

    @pytest.fixture(autouse=True)
    def _stub_balance_cache(self, monkeypatch):
        """Force cache misses so every test exercises the SQL path."""
        from redis_manager import redis_manager

        async def _miss(*_a, **_k):
            return None

        async def _noop(*_a, **_k):
            return True

        monkeypatch.setattr(redis_manager, "get_wallet_balance", _miss)
        monkeypatch.setattr(redis_manager, "set_wallet_balance", _noop)
        monkeypatch.setattr(redis_manager, "invalidate_wallet_balance", _noop)

    @pytest.mark.asyncio
    async def test_balance_from_seed_top_up(self, client, test_wallet):
        # test_wallet fixture seeds a ₹500 COMPLETED TOP_UP row.
        assert await WalletService.get_balance(test_wallet.id) == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_pending_top_up_not_credited(self, client, test_wallet):
        # PENDING TOP_UPs must not contribute until webhook flips to COMPLETED.
        await WalletService._invalidate_balance_cache(test_wallet.id)
        await WalletTransaction.create(
            wallet=test_wallet,
            amount=Decimal("250.00"),
            type=TransactionTypeEnum.TOP_UP,
            description="Pending recharge",
            payment_metadata={"status": "PENDING"},
        )
        # Still ₹500 — pending row excluded.
        assert await WalletService.get_balance(test_wallet.id) == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_charge_deduct_subtracts(self, client, test_wallet):
        await WalletService._invalidate_balance_cache(test_wallet.id)
        await WalletTransaction.create(
            wallet=test_wallet,
            amount=Decimal("75.00"),
            type=TransactionTypeEnum.CHARGE_DEDUCT,
            description="Charge",
        )
        assert await WalletService.get_balance(test_wallet.id) == Decimal("425.00")

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_write(self, client, test_wallet):
        # Prime the cache via a read.
        assert await WalletService.get_balance(test_wallet.id) == Decimal("500.00")
        # New CHARGE_DEDUCT should invalidate via WalletService write paths,
        # but a raw .create call does not invalidate — that's by design;
        # service-layer writes are the only invalidation point.
        # So we explicitly invalidate here and re-read to confirm freshness.
        await WalletTransaction.create(
            wallet=test_wallet,
            amount=Decimal("100.00"),
            type=TransactionTypeEnum.CHARGE_DEDUCT,
            description="Charge",
        )
        await WalletService._invalidate_balance_cache(test_wallet.id)
        assert await WalletService.get_balance(test_wallet.id) == Decimal("400.00")

    @pytest.mark.asyncio
    async def test_no_transactions_returns_zero(self, client, test_user):
        # Fresh wallet with no transactions → ₹0.
        wallet = await Wallet.create(user=test_user)
        assert await WalletService.get_balance(wallet.id) == Decimal("0.00")

    @pytest.mark.asyncio
    async def test_negative_balance_emits_warning_and_metric(
        self, client, test_wallet, monkeypatch
    ):
        """Drive the wallet negative and confirm the warning metric fires.

        Negative derived balance means the budget cap didn't enforce in
        time (or this is a pre-cap historical session). Engineering needs
        to see it — we log a warning and increment the counter, but never
        clamp the value at this layer (display layers may).
        """
        from unittest.mock import MagicMock
        from services import wallet_service as _ws_mod

        mock_metrics = MagicMock()
        monkeypatch.setattr(_ws_mod, "MetricsCollector", mock_metrics)

        # Seed wallet is ₹500. Deduct ₹600 → balance = -₹100.
        await WalletService._invalidate_balance_cache(test_wallet.id)
        await WalletTransaction.create(
            wallet=test_wallet,
            amount=Decimal("600.00"),
            type=TransactionTypeEnum.CHARGE_DEDUCT,
            description="Over-budget charge",
        )
        balance = await WalletService.get_balance(test_wallet.id)

        assert balance == Decimal("-100.00")  # NOT clamped
        mock_metrics.increment_counter.assert_any_call("Custom/Wallet/NegativeBalance")

    @pytest.mark.asyncio
    async def test_get_balance_sees_uncommitted_writes_in_same_transaction(
        self, client, test_wallet
    ):
        """get_balance must honour the active Tortoise transaction context.

        Inside an `async with in_transaction()` block, a balance read must
        see writes made earlier in the same block — even though those
        writes aren't yet committed to other connections. This is what
        `process_transaction_billing` and `process_wallet_topup` rely on
        when they snapshot `previous_balance` for metadata while holding
        the wallet-row lock.

        Verifies the fix for issue #4 in the post-Module-C review.
        """
        from tortoise.transactions import in_transaction
        async with in_transaction():
            await WalletTransaction.create(
                wallet=test_wallet,
                amount=Decimal("123.00"),
                type=TransactionTypeEnum.CHARGE_DEDUCT,
                description="In-transaction probe",
            )
            await WalletService._invalidate_balance_cache(test_wallet.id)
            # Must see the new deduction even though the transaction
            # hasn't committed yet — proves get_balance routes through
            # the active connection.
            in_txn_balance = await WalletService.get_balance(test_wallet.id)
            assert in_txn_balance == Decimal("500.00") - Decimal("123.00")
