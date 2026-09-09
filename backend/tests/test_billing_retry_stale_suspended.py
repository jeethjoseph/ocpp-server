"""Regression tests for BillingRetryService._cleanup_stale_suspended_transactions.

Incident (prod, 2026-06-18, txn 949): a disconnect-suspended QR session was
force-stopped by the billing-retry sweep ~9 min after disconnect, even though
the disconnect reconnect grace window was 30 min and the charger came back at
18.5 min. Root cause: the sweep used SUSPEND_TIMEOUT_SECONDS (5 min) as its
cutoff instead of the longest legitimate window.

Post ADR 0027 the windows are per-connector-type (policy.py): latched
connectors (Type2 — what the `test_charger` fixture has) get the 12h window,
unlatched sockets the 45min window. These tests pin the sweep to each row's
OWN window: inside-window rows survive, past-window rows are swept, and a
latched row is never swept at the socket cutoff.
"""
import pytest
import uuid
from datetime import datetime, timedelta, timezone

from services.billing_retry_service import BillingRetryService
from policy import (
    SUSPEND_WINDOW_LATCHED_SECONDS,
    SUSPEND_WINDOW_UNLATCHED_SECONDS,
    STALE_SUSPENDED_BUFFER_SECONDS,
)
from models import Charger, Connector, Transaction, TransactionStatusEnum


async def _make_socket_charger(test_station) -> Charger:
    charger = await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=test_station.id,
        name="Socket Sweep Charger",
        latest_status="Available",
    )
    await Connector.create(
        charger_id=charger.id, connector_id=1, connector_type="Socket"
    )
    return charger


class TestBillingRetryStaleSuspendedCutoff:
    """The billing-retry stale-suspended sweep must honor each transaction's
    own per-connector-type suspend window, not a shorter global one."""

    @pytest.mark.asyncio
    async def test_latched_txn_past_socket_window_survives(
        self, client, test_charger, test_user
    ):
        """The ADR 0027 core case: a Type2 (latched) txn suspended for longer
        than the SOCKET window must NOT be swept — its own window is 12h.
        Under a single global 45-min cutoff this txn would be force-stopped."""
        suspended_at = datetime.now(timezone.utc) - timedelta(
            seconds=SUSPEND_WINDOW_UNLATCHED_SECONDS + STALE_SUSPENDED_BUFFER_SECONDS + 300
        )
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        await BillingRetryService()._cleanup_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.SUSPENDED, \
            "Latched txn inside its 12h window must not be swept at the socket cutoff"

    @pytest.mark.asyncio
    async def test_socket_txn_within_own_window_survives(
        self, client, test_station, test_user
    ):
        """Incident shape (txn 949): a socket txn suspended ~9 min ago must
        NOT be swept — its window is 45 min."""
        socket_charger = await _make_socket_charger(test_station)
        suspended_at = datetime.now(timezone.utc) - timedelta(seconds=540)  # 9 min
        txn = await Transaction.create(
            charger=socket_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        await BillingRetryService()._cleanup_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status == TransactionStatusEnum.SUSPENDED, \
            "Socket txn inside its 45-min window must not be swept"

    @pytest.mark.asyncio
    async def test_socket_txn_past_own_window_is_swept(
        self, client, test_station, test_user, test_tariff, test_wallet
    ):
        """Backstop preserved: a socket txn suspended past its window + buffer
        IS still cleaned up."""
        socket_charger = await _make_socket_charger(test_station)
        suspended_at = datetime.now(timezone.utc) - timedelta(
            seconds=SUSPEND_WINDOW_UNLATCHED_SECONDS + STALE_SUSPENDED_BUFFER_SECONDS + 120
        )
        txn = await Transaction.create(
            charger=socket_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        await BillingRetryService()._cleanup_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status in (
            TransactionStatusEnum.STOPPED,
            TransactionStatusEnum.BILLING_FAILED,
        ), "Socket txn past its own window + buffer should be swept"

    @pytest.mark.asyncio
    async def test_latched_txn_past_own_window_is_swept(
        self, client, test_charger, test_user, test_tariff, test_wallet
    ):
        """Backstop preserved on the latched side too: past 12h + buffer the
        Type2 txn is cleaned up."""
        suspended_at = datetime.now(timezone.utc) - timedelta(
            seconds=SUSPEND_WINDOW_LATCHED_SECONDS + STALE_SUSPENDED_BUFFER_SECONDS + 120
        )
        txn = await Transaction.create(
            charger=test_charger,
            user=test_user,
            transaction_status=TransactionStatusEnum.SUSPENDED,
            suspended_at=suspended_at,
            start_meter_kwh=0.0,
        )

        await BillingRetryService()._cleanup_stale_suspended_transactions()

        refreshed = await Transaction.get(id=txn.id)
        assert refreshed.transaction_status in (
            TransactionStatusEnum.STOPPED,
            TransactionStatusEnum.BILLING_FAILED,
        ), "Latched txn past its own window + buffer should be swept"
