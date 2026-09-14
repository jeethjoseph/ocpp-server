"""Reconcile TRANSFER_PROCESSED ledger rows against Razorpay by polling.

The webhook path (``settlement.processed`` → list its transfers) is the fast
signal. This is the honest backstop for the cases it cannot cover: a webhook
dropped or never delivered, a settlement that failed and was retried, or —
the reason this module exists — three months of events whose handler read a
field that does not exist, leaving 377 rows one step short of SETTLED.

Each pass fetches every still-PROCESSED transfer older than the age floor with
``?expand[]=recipient_settlement`` and advances it through the same strict
predicate the webhook uses (``FranchiseeSettlementService.settle_from_transfer``),
so the two paths cannot disagree about what "settled" means.

Why an age floor: linked accounts settle on the parent's T+n schedule, and a
held transfer only settles the business day after the hold lifts. Polling a
row minutes after ``transfer.processed`` is a wasted call with a predictable
answer. Observed lag on this account is T+3 (processed 30 May, settled 2 June
2026), so the floor sits just under it at two days and the sweep runs every six
hours: a row is examined at most a couple of times before it settles, and a
dropped webhook is reconciled within a day rather than within four. Volume is
a few dozen transfers a day across both environments, so the cost is a handful
of GETs per pass against a 500-row cap. The backfill runs once with no floor.

Same lifecycle shape as ``stuck_payout_detector`` — start/stop/_loop/_sweep —
so the two are wired and reasoned about identically. Cadence and floor are
policy, not deployment wiring, and so are constants here rather than env vars
(the ADR 0027 rule).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from utils import safe_create_task

logger = logging.getLogger("ocpp-server")

SWEEP_INTERVAL_SECONDS = 6 * 3600
AGE_FLOOR_DAYS = 2
# Bounds the Razorpay calls one pass may make. A pass that hits the cap logs
# and stops; the next one picks up where it left off, oldest rows first.
MAX_ROWS_PER_SWEEP = 500


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
    entries = await query.order_by("transfer_processed_at").limit(limit).all()

    counts = {"examined": len(entries), "settled": 0, "unsettled": 0, "errors": 0}
    for entry in entries:
        try:
            transfer = await razorpay_service.fetch_transfer_with_settlement(
                entry.razorpay_transfer_id
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
            "Settlement reconcile hit the %s-row cap; remaining rows next pass", limit
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
    global _reconciler
    if _reconciler is None:
        _reconciler = SettlementReconciler()
    await _reconciler.start()


async def stop_settlement_reconciler():
    if _reconciler is not None:
        await _reconciler.stop()
