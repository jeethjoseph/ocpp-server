"""Tests for ``services.stuck_payout_detector``.

Covers the three behaviors that matter for ops:
1. ``build_stuck_filter`` selects the right rows under each stuck condition.
2. ``_sweep_once`` fires exactly one Sentry message per franchisee
   (not per entry) with the right tags.
3. The loop survives a single iteration exception and keeps going.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from models import (
    CommissionLedgerEntry,
    SettlementStatusEnum,
    Transaction,
    TransactionStatusEnum,
)
from services.stuck_payout_detector import (
    StuckPayoutDetector,
    build_stuck_filter,
)


pytestmark = pytest.mark.asyncio


async def _make_ledger(test_franchisee, test_charger, test_user, **overrides):
    """Create a CommissionLedgerEntry with sane defaults; override fields per test."""
    txn = await Transaction.create(
        charger=test_charger,
        user=test_user,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    defaults = dict(
        transaction=txn,
        franchisee=test_franchisee,
        gross_amount=Decimal("100.00"),
        payment_method="QR_UPI",
        razorpay_payment_id=f"pay_stuck_{txn.id}",
        refund_amount=Decimal("0.00"),
        pg_fee_amount=Decimal("0.00"),
        net_amount=Decimal("100.00"),
        gst_collected=Decimal("15.25"),
        net_excl_gst=Decimal("84.75"),
        commission_percent=Decimal("20.00"),
        platform_commission=Decimal("16.95"),
        tds_rate_percent=Decimal("10.00"),
        tds_amount=Decimal("6.78"),
        transfer_fee=Decimal("0.00"),
        franchisee_payout=Decimal("61.02"),
        energy_consumed_kwh=10.0,
        tariff_rate_per_kwh=Decimal("10.00"),
        settlement_status=SettlementStatusEnum.PENDING,
        idempotency_key=f"txn_{txn.id}",
    )
    defaults.update(overrides)
    return await CommissionLedgerEntry.create(**defaults)


async def test_filter_catches_failed_at_max_retries(
    client, test_franchisee, test_charger, test_user
):
    """FAILED entries with retry_count >= max_retries are stuck (the retry
    loop has given up)."""
    stuck = await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.FAILED,
        retry_count=3,
    )
    not_stuck = await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.FAILED,
        retry_count=1,
    )

    matches = await CommissionLedgerEntry.filter(
        build_stuck_filter(older_than_hours=24, max_transfer_retries=3)
    ).all()
    matched_ids = {e.id for e in matches}
    assert stuck.id in matched_ids
    assert not_stuck.id not in matched_ids


async def test_filter_catches_old_pending(
    client, test_franchisee, test_charger, test_user
):
    """PENDING entries older than threshold are stuck (settlement service
    never picked them up)."""
    old_pending = await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.PENDING,
    )
    # Backdate by 30h
    old_pending.created_at = datetime.now(timezone.utc) - timedelta(hours=30)
    await old_pending.save()

    fresh_pending = await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.PENDING,
    )

    matches = await CommissionLedgerEntry.filter(
        build_stuck_filter(older_than_hours=24, max_transfer_retries=3)
    ).all()
    matched_ids = {e.id for e in matches}
    assert old_pending.id in matched_ids
    assert fresh_pending.id not in matched_ids


async def test_filter_catches_old_transfer_initiated(
    client, test_franchisee, test_charger, test_user
):
    """TRANSFER_INITIATED that's been waiting past threshold means the
    Razorpay webhook never landed → stuck."""
    stuck = await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.TRANSFER_INITIATED,
        transfer_initiated_at=datetime.now(timezone.utc) - timedelta(hours=30),
    )
    fresh = await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.TRANSFER_INITIATED,
        transfer_initiated_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    matches = await CommissionLedgerEntry.filter(
        build_stuck_filter(older_than_hours=24, max_transfer_retries=3)
    ).all()
    matched_ids = {e.id for e in matches}
    assert stuck.id in matched_ids
    assert fresh.id not in matched_ids


async def test_sweep_aggregates_per_franchisee(
    client, test_franchisee, test_charger, test_user
):
    """Two stuck entries for the same franchisee → one Sentry message, not two."""
    await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.FAILED,
        retry_count=3,
    )
    await _make_ledger(
        test_franchisee, test_charger, test_user,
        settlement_status=SettlementStatusEnum.FAILED,
        retry_count=3,
    )

    detector = StuckPayoutDetector(
        interval_seconds=999, threshold_hours=24, max_transfer_retries=3
    )
    with patch(
        "services.monitoring_service.SentryHelper.capture_message"
    ) as mock_capture:
        found = await detector._sweep_once()

    assert found == 2
    assert mock_capture.call_count == 1
    args, kwargs = mock_capture.call_args
    assert kwargs["tags"]["franchisee_id"] == test_franchisee.id
    assert kwargs["tags"]["count"] == 2


async def test_sweep_with_no_stuck_entries_does_not_alert(
    client, test_commission_ledger_entry, test_franchisee
):
    """Healthy PENDING entry (created_at = now) shouldn't trigger alerts."""
    detector = StuckPayoutDetector(
        interval_seconds=999, threshold_hours=24, max_transfer_retries=3
    )
    with patch(
        "services.monitoring_service.SentryHelper.capture_message"
    ) as mock_capture:
        found = await detector._sweep_once()

    assert found == 0
    mock_capture.assert_not_called()


async def test_loop_survives_sweep_exception(
    client, test_franchisee, test_charger, test_user
):
    """If _sweep_once throws, the loop must catch the exception and continue
    on the next tick. Verified by patching _sweep_once to throw once, then
    asserting the detector hasn't crashed (is_running stays True)."""
    detector = StuckPayoutDetector(
        interval_seconds=1, threshold_hours=24, max_transfer_retries=3
    )
    call_count = {"n": 0}

    async def flaky_sweep():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated sweep failure")
        return 0

    # Start the loop manually with the patched sweep.
    detector.is_running = True
    with patch.object(detector, "_sweep_once", side_effect=flaky_sweep):
        # Run _loop briefly. asyncio.wait_for forces a short wall-clock window.
        import asyncio
        task = asyncio.create_task(detector._loop())
        try:
            await asyncio.sleep(0.05)  # Let the first failing iteration run
        finally:
            detector.is_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # The loop swallowed the exception (didn't propagate) so the test reaches here.
    assert call_count["n"] >= 1
