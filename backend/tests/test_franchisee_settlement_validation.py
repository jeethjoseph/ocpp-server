"""Integration tests for FranchiseeSettlementService._validate_ledger_for_transfer
plus initiate_transfer endpoint routing.

Uses the test_franchisee + test_commission_ledger_entry fixtures from
conftest; all DB-backed so the razorpay_payment_id collision check (which
queries CommissionLedgerEntry) hits a real schema.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.franchisee_settlement_service import (
    FranchiseeSettlementService,
    MAX_TRANSFER_RETRIES,
)
from models import CommissionLedgerEntry, SettlementStatusEnum


pytestmark = pytest.mark.asyncio


async def test_validator_happy_path(
    client, test_commission_ledger_entry, test_franchisee
):
    """Default fixture state should pass all checks."""
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure is None


async def test_validator_rejects_non_positive_payout(
    client, test_commission_ledger_entry, test_franchisee
):
    test_commission_ledger_entry.franchisee_payout = Decimal("0.00")
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_payout_not_positive"


async def test_validator_rejects_payout_exceeding_net_paid(
    client, test_commission_ledger_entry, test_franchisee
):
    test_commission_ledger_entry.refund_amount = Decimal("950.00")
    # payout (610.17) now > gross (1000) - refund (950) = 50
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_payout_exceeds_net_paid"


async def test_validator_rejects_components_not_summing_to_gross(
    client, test_commission_ledger_entry, test_franchisee
):
    # Inflate platform_commission so the component sum overshoots gross.
    test_commission_ledger_entry.platform_commission = Decimal("500.00")
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_components_do_not_sum_to_gross"


async def test_validator_rejects_terminal_status(
    client, test_commission_ledger_entry, test_franchisee
):
    test_commission_ledger_entry.settlement_status = (
        SettlementStatusEnum.TRANSFER_PROCESSED
    )
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_terminal_status_TRANSFER_PROCESSED"


async def test_validator_rejects_below_threshold_status(
    client, test_commission_ledger_entry, test_franchisee
):
    """BELOW_THRESHOLD is terminal — sub-floor payouts must never
    be retried by the validator or the retry sweep."""
    test_commission_ledger_entry.settlement_status = (
        SettlementStatusEnum.BELOW_THRESHOLD
    )
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_terminal_status_BELOW_THRESHOLD"


async def test_validator_rejects_franchisee_account_mismatch(
    client, test_commission_ledger_entry, test_franchisee
):
    test_franchisee.razorpay_account_id = None
    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_franchisee_account_mismatch"


async def test_validator_rejects_payment_id_already_transferred(
    client, test_commission_ledger_entry, test_franchisee, test_charger,
    test_user,
):
    """A second ledger entry that already carries a razorpay_transfer_id
    for the same razorpay_payment_id should block this entry from
    transferring."""
    from models import Transaction, TransactionStatusEnum
    sibling_txn = await Transaction.create(
        charger=test_charger,
        user=test_user,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    await CommissionLedgerEntry.create(
        transaction=sibling_txn,
        franchisee=test_franchisee,
        gross_amount=Decimal("100.00"),
        payment_method="QR_UPI",
        razorpay_payment_id=test_commission_ledger_entry.razorpay_payment_id,
        refund_amount=Decimal("0.00"),
        pg_fee_amount=Decimal("0.00"),
        net_amount=Decimal("100.00"),
        gst_collected=Decimal("0.00"),
        net_excl_gst=Decimal("100.00"),
        commission_percent=Decimal("20.00"),
        platform_commission=Decimal("20.00"),
        tds_rate_percent=Decimal("10.00"),
        tds_amount=Decimal("10.00"),
        transfer_fee=Decimal("0.00"),
        franchisee_payout=Decimal("70.00"),
        energy_consumed_kwh=2.0,
        tariff_rate_per_kwh=Decimal("15.00"),
        settlement_status=SettlementStatusEnum.TRANSFER_PROCESSED,
        razorpay_transfer_id="trf_already_done",
        idempotency_key=f"txn_{sibling_txn.id}",
    )

    failure = (
        await FranchiseeSettlementService._validate_ledger_for_transfer(
            test_commission_ledger_entry, test_franchisee
        )
    )
    assert failure == "validation_payment_id_already_transferred"


# ─── initiate_transfer endpoint routing ─────────────────────────────────


async def test_initiate_transfer_uses_payment_endpoint_for_qr(
    client, test_commission_ledger_entry, test_franchisee
):
    """QR ledger entries (razorpay_payment_id set) must call
    create_payment_transfer; the direct create_transfer must NOT fire.
    The synchronous response's fees/tax must be captured into
    transfer_fee, and any stale failure_reason must be cleared."""
    test_commission_ledger_entry.razorpay_payment_id = "pay_qr_test"
    test_commission_ledger_entry.failure_reason = "stale error from prior retry"
    await test_commission_ledger_entry.save()

    with patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_payment_transfer = AsyncMock(
            return_value={"id": "trf_via_payment", "fees": 2, "tax": 0}
        )
        mock_rzp.create_transfer = AsyncMock(
            return_value={"id": "trf_direct"}
        )

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is True
    mock_rzp.create_payment_transfer.assert_awaited_once()
    mock_rzp.create_transfer.assert_not_awaited()
    call_kwargs = mock_rzp.create_payment_transfer.await_args.kwargs
    assert call_kwargs["payment_id"] == "pay_qr_test"
    assert call_kwargs["account_id"] == test_franchisee.razorpay_account_id

    refreshed = await CommissionLedgerEntry.get(id=test_commission_ledger_entry.id)
    assert refreshed.razorpay_transfer_id == "trf_via_payment"
    assert refreshed.settlement_status == SettlementStatusEnum.TRANSFER_INITIATED
    assert refreshed.transfer_fee == Decimal("0.02")
    assert refreshed.failure_reason is None


async def test_initiate_transfer_uses_direct_endpoint_for_wallet(
    client, test_commission_ledger_entry, test_franchisee
):
    """Wallet ledger entries (no razorpay_payment_id) must fall back to
    direct create_transfer; create_payment_transfer must NOT fire. Requires
    WALLET_SETTLEMENT_ENABLED=True; the gate is exercised separately."""
    test_commission_ledger_entry.razorpay_payment_id = None
    test_commission_ledger_entry.payment_method = "WALLET"
    await test_commission_ledger_entry.save()

    with patch(
        "services.franchisee_settlement_service.WALLET_SETTLEMENT_ENABLED",
        True,
    ), patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_payment_transfer = AsyncMock(
            return_value={"id": "trf_via_payment"}
        )
        mock_rzp.create_transfer = AsyncMock(
            return_value={"id": "trf_direct"}
        )

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is True
    mock_rzp.create_transfer.assert_awaited_once()
    mock_rzp.create_payment_transfer.assert_not_awaited()

    refreshed = await CommissionLedgerEntry.get(id=test_commission_ledger_entry.id)
    assert refreshed.razorpay_transfer_id == "trf_direct"
    assert refreshed.settlement_status == SettlementStatusEnum.TRANSFER_INITIATED


async def test_initiate_transfer_holds_wallet_when_flag_disabled(
    client, test_commission_ledger_entry, test_franchisee
):
    """Wallet ledger entry with WALLET_SETTLEMENT_ENABLED=False must park
    ON_HOLD with the documented failure_reason and never contact Razorpay."""
    test_commission_ledger_entry.razorpay_payment_id = None
    test_commission_ledger_entry.payment_method = "WALLET"
    await test_commission_ledger_entry.save()

    with patch(
        "services.franchisee_settlement_service.WALLET_SETTLEMENT_ENABLED",
        False,
    ), patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_payment_transfer = AsyncMock()
        mock_rzp.create_transfer = AsyncMock()

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is False
    mock_rzp.create_payment_transfer.assert_not_awaited()
    mock_rzp.create_transfer.assert_not_awaited()

    refreshed = await CommissionLedgerEntry.get(id=test_commission_ledger_entry.id)
    assert refreshed.settlement_status == SettlementStatusEnum.ON_HOLD
    assert refreshed.failure_reason == "wallet_settlement_not_activated"


async def test_retry_sweep_skips_wallet_entries_when_flag_disabled(
    client, test_commission_ledger_entry, test_franchisee
):
    """retry_failed_transfers must not loop on wallet entries while the
    feature is gated off. Without this filter the entries would re-attempt
    and re-fail on every retry cycle, exhausting MAX_TRANSFER_RETRIES."""
    test_commission_ledger_entry.razorpay_payment_id = None
    test_commission_ledger_entry.payment_method = "WALLET"
    test_commission_ledger_entry.settlement_status = SettlementStatusEnum.ON_HOLD
    test_commission_ledger_entry.failure_reason = "wallet_settlement_not_activated"
    await test_commission_ledger_entry.save()

    with patch(
        "services.franchisee_settlement_service.WALLET_SETTLEMENT_ENABLED",
        False,
    ), patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_transfer = MagicMock(return_value={"id": "should_not_fire"})

        success, total = await FranchiseeSettlementService.retry_failed_transfers()

    assert (success, total) == (0, 0)
    mock_rzp.create_transfer.assert_not_called()


async def test_initiate_transfer_skips_when_status_changed_mid_flight(
    client, test_commission_ledger_entry, test_franchisee
):
    """Regression for the retry-sweep race: between the SELECT in
    retry_failed_transfers and the SDK call inside initiate_transfer,
    a webhook may flip the entry to TRANSFER_PROCESSED. The in-memory
    object still says transferable; the DB row no longer does. The
    last-mile re-fetch must catch this and bail without calling
    Razorpay."""
    # In-memory object reflects an old transferable state.
    test_commission_ledger_entry.settlement_status = SettlementStatusEnum.PENDING
    # Simulate the concurrent webhook by directly flipping the DB row.
    await CommissionLedgerEntry.filter(
        id=test_commission_ledger_entry.id
    ).update(settlement_status=SettlementStatusEnum.TRANSFER_PROCESSED)

    with patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_payment_transfer = AsyncMock(
            return_value={"id": "should_not_fire"}
        )
        mock_rzp.create_transfer = MagicMock(
            return_value={"id": "should_not_fire"}
        )

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is False
    mock_rzp.create_payment_transfer.assert_not_awaited()
    mock_rzp.create_transfer.assert_not_called()
    refreshed = await CommissionLedgerEntry.get(
        id=test_commission_ledger_entry.id
    )
    assert refreshed.settlement_status == SettlementStatusEnum.TRANSFER_PROCESSED


async def test_initiate_transfer_saturates_retry_count_on_validation_failure(
    client, test_commission_ledger_entry, test_franchisee
):
    """When the pre-flight validator rejects an entry, retry_count must
    saturate to MAX_TRANSFER_RETRIES so the retry sweep stops re-picking
    it. Pre-fix the entry stayed at retry_count=0 forever; the sweep
    re-evaluated it every interval and the rejection log fired every
    tick — 18 Sentry events in 3h on staging 2026-05-26 from a single
    ledger entry. Detector still surfaces these via FAILED+retry_count
    >=max branch, so admin visibility is preserved.
    """
    test_commission_ledger_entry.franchisee_payout = Decimal("0.00")
    await test_commission_ledger_entry.save()

    with patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_payment_transfer = AsyncMock()
        mock_rzp.create_transfer = MagicMock()

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is False
    mock_rzp.create_payment_transfer.assert_not_awaited()
    mock_rzp.create_transfer.assert_not_called()

    refreshed = await CommissionLedgerEntry.get(
        id=test_commission_ledger_entry.id
    )
    assert refreshed.settlement_status == SettlementStatusEnum.FAILED
    assert refreshed.failure_reason == "validation_payout_not_positive"
    assert refreshed.retry_count == MAX_TRANSFER_RETRIES

    # The retry sweep query is `status IN (FAILED, ON_HOLD) AND
    # retry_count < MAX_TRANSFER_RETRIES`. Saturating retry_count to the
    # threshold pushes the entry out of the sweep net immediately.
    with patch("services.razorpay_service.razorpay_service") as mock_rzp2:
        mock_rzp2.is_route_enabled.return_value = True
        mock_rzp2.create_payment_transfer = AsyncMock()
        mock_rzp2.create_transfer = MagicMock()
        success, total = (
            await FranchiseeSettlementService.retry_failed_transfers()
        )
    assert (success, total) == (0, 0)
    mock_rzp2.create_payment_transfer.assert_not_awaited()
    mock_rzp2.create_transfer.assert_not_called()
