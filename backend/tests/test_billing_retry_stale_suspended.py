"""Regression tests for BillingRetryService._cleanup_stale_suspended_transactions.

Incident (prod, 2026-06-18, txn 949): a disconnect-suspended QR session was
force-stopped by the billing-retry sweep ~9 min after disconnect, even though
the disconnect reconnect grace window was 30 min and the charger came back at
18.5 min. Root cause: the sweep used SUSPEND_TIMEOUT_SECONDS (5 min) as its
cutoff instead of the longest legitimate window. These tests pin the sweep to
the max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60 behavior.
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services import disconnect_handler
from services.billing_retry_service import BillingRetryService
from models import Transaction, TransactionStatusEnum


class TestBillingRetryStaleSuspendedCutoff:
    """The billing-retry stale-suspended sweep must honor the longest suspend
    window, not the short reboot-resume window."""

    @pytest.mark.asyncio
    async def test_disconnect_suspended_within_window_survives(
        self, client, test_charger, test_user
    ):
        """Incident shape: a txn disconnect-suspended ~9 min ago must NOT be
        swept when the disconnect window is 30 min."""
        suspended_at = datetime.now(timezone.utc) - timedelta(seconds=540)  # 9 min
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        # Prod-like disconnect window (30 min). Under the pre-fix 5-min cutoff
        # this txn would have been force-stopped.
        with patch.object(disconnect_handler, "DISCONNECT_SUSPEND_TIMEOUT", 1800), \
                patch.object(disconnect_handler, "SUSPEND_TIMEOUT", 300):
            await BillingRetryService()._cleanup_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.SUSPENDED, \
            "Disconnect-suspended txn inside the 30-min window must not be swept"

    @pytest.mark.asyncio
    async def test_suspended_past_max_window_is_swept(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Backstop preserved: a txn suspended past the max window + buffer IS
        still cleaned up."""
        suspended_at = datetime.now(timezone.utc) - timedelta(seconds=2000)  # > 1860s
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        with patch.object(disconnect_handler, "DISCONNECT_SUSPEND_TIMEOUT", 1800), \
                patch.object(disconnect_handler, "SUSPEND_TIMEOUT", 300):
            await BillingRetryService()._cleanup_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status in (
            TransactionStatusEnum.STOPPED,
            TransactionStatusEnum.BILLING_FAILED,
        ), "Txn past the max window + buffer should be swept"
