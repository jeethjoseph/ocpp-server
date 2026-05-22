"""Background driver that periodically retries ON_HOLD / FAILED franchisee
payouts.

The actual retry logic lives in
``FranchiseeSettlementService.retry_failed_transfers`` — this service is a
thin scheduler that wakes every ``FRANCHISEE_PAYOUT_RETRY_INTERVAL_SECONDS``
and asks the settlement service to drain its retry queue. Closes the loop
on entries that were parked because of cooling-period or
funds_on_hold/transfers_disabled gates that have since cleared.
"""
import asyncio
import logging
import os

from utils import safe_create_task

logger = logging.getLogger(__name__)


class FranchiseePayoutRetryService:
    def __init__(self, interval_seconds: int = 600):
        self.interval_seconds = interval_seconds
        self.is_running = False
        self._task = None

    async def start(self):
        if self.is_running:
            logger.warning("Franchisee payout retry service already running")
            return
        self.is_running = True
        self._task = safe_create_task(self._loop())
        logger.info(
            "✅ Started franchisee_payout_retry_service (interval: %ds)",
            self.interval_seconds,
        )

    async def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("🛑 Stopped franchisee_payout_retry_service")

    async def _loop(self):
        # Defer the import so this module stays importable even if the
        # settlement service has its own circular-import surprises.
        from services.franchisee_settlement_service import (
            FranchiseeSettlementService,
        )
        while self.is_running:
            try:
                success, total = (
                    await FranchiseeSettlementService.retry_failed_transfers()
                )
                if total:
                    logger.info(
                        "Payout retry tick: %d/%d entries advanced",
                        success, total,
                    )
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "❌ Error in franchisee_payout_retry loop: %s",
                    e, exc_info=True,
                )
                # Back off on unexpected errors so we don't tight-loop.
                await asyncio.sleep(min(60, self.interval_seconds))


_payout_retry_service = None


async def start_franchisee_payout_retry_service():
    """Start the background retry loop. No-op when
    ``RAZORPAY_ROUTE_ENABLED`` is not "true" so disabled environments
    don't churn."""
    global _payout_retry_service

    if os.getenv("RAZORPAY_ROUTE_ENABLED", "false").lower() != "true":
        logger.info(
            "RAZORPAY_ROUTE_ENABLED != true; skipping payout retry service"
        )
        return

    interval = int(
        os.getenv("FRANCHISEE_PAYOUT_RETRY_INTERVAL_SECONDS", "600")
    )
    if _payout_retry_service is None:
        _payout_retry_service = FranchiseePayoutRetryService(
            interval_seconds=interval
        )
    await _payout_retry_service.start()


async def stop_franchisee_payout_retry_service():
    global _payout_retry_service
    if _payout_retry_service:
        await _payout_retry_service.stop()
