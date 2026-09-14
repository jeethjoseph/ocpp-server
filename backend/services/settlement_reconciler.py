"""Reconcile TRANSFER_PROCESSED ledger rows against Razorpay by polling.

The webhook path (``settlement.processed`` → list its transfers) is the fast
signal. This is the honest backstop for the cases it cannot cover: a webhook
dropped or never delivered, a settlement that failed and was retried, or —
the reason this module exists — three months of events whose handler read a
field that does not exist, leaving 377 rows one step short of SETTLED.

Each pass fetches every still-PROCESSED transfer older than the age floor with
its recipient settlement expanded and advances it through the same strict
predicate the webhook uses (``FranchiseeSettlementService.settle_from_transfer``),
so the two paths cannot disagree about what "settled" means.

Ordering is NEWEST-processed first, deliberately. A row that can never settle
— its recipient settlement failed, its linked account is deactivated, its
transfer id 404s — is re-examined every pass and never leaves this pool, so
oldest-first would let such rows crowd the head of the queue and starve the
rows that actually settled. Newest-first means the live rows are always
examined; the permanently-stuck tail is what a tight budget cuts, and that
tail is exactly what the STUCK_PROCESSED_DAYS alarm exists to surface to a
human. There is no cursor and there deliberately is no state: a pass that hits
the budget re-examines from the newest again next time.

Cadence and floor live in ``policy.py`` beside the stuck threshold, because the
three have an ordering (floor < alarm) that is easy to break one at a time —
the drift ADR 0027 was written to stop. The backfill runs once with no floor.

Same lifecycle shape as ``stuck_payout_detector`` — start/stop/_loop/_sweep —
and the same gate: a no-op unless Route is enabled, so a dev box restored
from a production dump does not poll api.razorpay.com every six hours.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from policy import (
    SETTLEMENT_AGE_FLOOR_DAYS as AGE_FLOOR_DAYS,
    SETTLEMENT_SWEEP_INTERVAL_SECONDS as SWEEP_INTERVAL_SECONDS,
    STUCK_PROCESSED_DAYS,
)
from utils import safe_create_task

logger = logging.getLogger("ocpp-server")

# Bounds the Razorpay calls one pass may make. Not policy — an operational
# safety cap against a runaway backlog. At a few dozen transfers a day it is
# never reached in steady state; a pass that does reach it warns, because the
# rows it could not examine are the oldest ones and the alarm is what covers
# those.
MAX_ROWS_PER_SWEEP = 1000


async def reconcile_processed_transfers(
    *, age_floor_days: Optional[int] = AGE_FLOOR_DAYS, limit: int = MAX_ROWS_PER_SWEEP
) -> dict:
    """One reconciliation pass. Returns counts for the log and for tests.

    ``age_floor_days=None`` disables the floor — the backfill mode.
    """
    from models import CommissionLedgerEntry, SettlementStatusEnum
    from services.franchisee_settlement_service import FranchiseeSettlementService
    from services.razorpay_service import razorpay_service

    query = CommissionLedgerEntry.filter(
        settlement_status=SettlementStatusEnum.TRANSFER_PROCESSED,
        razorpay_transfer_id__not_isnull=True,
    )
    if age_floor_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=age_floor_days)
        query = query.filter(transfer_processed_at__lt=cutoff)
    entries = await query.order_by("-transfer_processed_at").limit(limit).all()

    counts = {"examined": len(entries), "settled": 0, "unsettled": 0, "errors": 0}
    for entry in entries:
        try:
            transfer = await razorpay_service.fetch_transfer(
                entry.razorpay_transfer_id, expand_settlement=True
            )
        except Exception as exc:
            counts["errors"] += 1
            logger.warning(
                "Reconcile: could not fetch transfer %s for entry %s: %s",
                entry.razorpay_transfer_id, entry.id, exc,
            )
            continue
        if await FranchiseeSettlementService.settle_from_transfer(transfer):
            counts["settled"] += 1
        else:
            counts["unsettled"] += 1

    if counts["examined"]:
        logger.info("Settlement reconcile pass: %s", counts)
    if counts["examined"] >= limit:
        logger.warning(
            "Settlement reconcile hit the %s-call budget; the oldest rows were "
            "not examined this pass — if they are stuck, the %s-day alarm covers them",
            limit, STUCK_PROCESSED_DAYS,
        )
    return counts


class SettlementReconciler:
    def __init__(self, interval_seconds: int = SWEEP_INTERVAL_SECONDS):
        self.interval_seconds = interval_seconds
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self.is_running:
            logger.warning("Settlement reconciler already running")
            return
        self.is_running = True
        self._task = safe_create_task(self._loop())
        logger.info(
            "✅ Started settlement_reconciler (interval=%ds, floor=%dd)",
            self.interval_seconds, AGE_FLOOR_DAYS,
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
        logger.info("🛑 Stopped settlement_reconciler")

    async def _loop(self):
        while self.is_running:
            try:
                await reconcile_processed_transfers()
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("❌ Error in settlement_reconciler loop: %s", e, exc_info=True)
                await asyncio.sleep(min(300, self.interval_seconds))


_reconciler: Optional[SettlementReconciler] = None


async def start_settlement_reconciler():
    """Start the background sweep. No-op unless Razorpay Route is enabled —
    the same gate as ``stuck_payout_detector``. Without it a dev or CI box
    holding TRANSFER_PROCESSED rows (a DB restored from a production dump) would
    hit the real API every six hours, or log an error per row forever."""
    global _reconciler
    from services.razorpay_service import razorpay_service

    if not razorpay_service.is_route_enabled():
        logger.info("Razorpay Route not enabled; skipping settlement_reconciler")
        return
    if _reconciler is None:
        _reconciler = SettlementReconciler()
    await _reconciler.start()


async def stop_settlement_reconciler():
    if _reconciler is not None:
        await _reconciler.stop()
