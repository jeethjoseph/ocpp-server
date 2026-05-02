"""Integration tests for FranchiseeSettlementService._validate_ledger_for_transfer
plus initiate_transfer endpoint routing.

Uses the test_franchisee + test_commission_ledger_entry fixtures from
conftest; all DB-backed so the razorpay_payment_id collision check (which
queries CommissionLedgerEntry) hits a real schema.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.franchisee_settlement_service import FranchiseeSettlementService
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
    # payout (593.22) now > gross (1000) - refund (950) = 50
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
        mock_rzp.create_transfer = MagicMock(
            return_value={"id": "trf_direct"}
        )

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is True
    mock_rzp.create_payment_transfer.assert_awaited_once()
    mock_rzp.create_transfer.assert_not_called()
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
    direct create_transfer; create_payment_transfer must NOT fire."""
    test_commission_ledger_entry.razorpay_payment_id = None
    test_commission_ledger_entry.payment_method = "WALLET"
    await test_commission_ledger_entry.save()

    with patch("services.razorpay_service.razorpay_service") as mock_rzp:
        mock_rzp.is_route_enabled.return_value = True
        mock_rzp.create_payment_transfer = AsyncMock(
            return_value={"id": "trf_via_payment"}
        )
        mock_rzp.create_transfer = MagicMock(
            return_value={"id": "trf_direct"}
        )

        ok = await FranchiseeSettlementService.initiate_transfer(
            test_commission_ledger_entry
        )

    assert ok is True
    mock_rzp.create_transfer.assert_called_once()
    mock_rzp.create_payment_transfer.assert_not_awaited()

    refreshed = await CommissionLedgerEntry.get(id=test_commission_ledger_entry.id)
    assert refreshed.razorpay_transfer_id == "trf_direct"
    assert refreshed.settlement_status == SettlementStatusEnum.TRANSFER_INITIATED
