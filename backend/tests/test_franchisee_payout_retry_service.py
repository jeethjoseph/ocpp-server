"""Tests for the background franchisee payout retry service.

Three behaviours covered:
1. start_*() is a no-op when RAZORPAY_ROUTE_ENABLED != "true"
2. start_*() bootstraps the service when route is enabled
3. The retry loop drives FranchiseeSettlementService.retry_failed_transfers
"""
import asyncio

import pytest

from services import franchisee_payout_retry_service as svc
from services.franchisee_settlement_service import FranchiseeSettlementService


pytestmark = pytest.mark.asyncio


async def test_start_skips_when_route_disabled(monkeypatch):
    """When RAZORPAY_ROUTE_ENABLED is not 'true', the service must not
    boot — disabled environments shouldn't spin a retry loop."""
    monkeypatch.setenv("RAZORPAY_ROUTE_ENABLED", "false")
    svc._payout_retry_service = None
    await svc.start_franchisee_payout_retry_service()
    assert svc._payout_retry_service is None


async def test_start_bootstraps_when_route_enabled(monkeypatch):
    """When the env flag is set, the singleton is created and start()
    is awaited. Stop afterwards so the loop doesn't leak into other tests."""
    monkeypatch.setenv("RAZORPAY_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FRANCHISEE_PAYOUT_RETRY_INTERVAL_SECONDS", "300")
    svc._payout_retry_service = None

    # Mock retry_failed_transfers so the loop body doesn't hit the DB.
    async def _fake_retry(franchisee_id=None):
        return (0, 0)
    monkeypatch.setattr(
        FranchiseeSettlementService,
        "retry_failed_transfers",
        _fake_retry,
    )

    await svc.start_franchisee_payout_retry_service()
    try:
        assert svc._payout_retry_service is not None
        assert svc._payout_retry_service.is_running is True
        assert svc._payout_retry_service.interval_seconds == 300
    finally:
        await svc.stop_franchisee_payout_retry_service()
        svc._payout_retry_service = None


async def test_loop_calls_retry_failed_transfers(monkeypatch):
    """The internal loop must drive retry_failed_transfers at least once
    per tick."""
    call_count = 0

    async def _fake_retry(franchisee_id=None):
        nonlocal call_count
        call_count += 1
        return (0, 0)

    monkeypatch.setattr(
        FranchiseeSettlementService,
        "retry_failed_transfers",
        _fake_retry,
    )

    service = svc.FranchiseePayoutRetryService(interval_seconds=300)
    await service.start()
    try:
        # Yield enough times for the loop to enter and call retry once.
        # safe_create_task schedules the loop on the event loop; a few
        # awaits let it run before we stop.
        for _ in range(5):
            await asyncio.sleep(0)
            if call_count > 0:
                break
    finally:
        await service.stop()

    assert call_count >= 1
