"""Background sweep that detects franchisee payouts which are stuck and
fires a Sentry warning so ops can triage them.

Complements ``FranchiseePayoutRetryService`` (which advances retryable
entries) by paging when an entry has not progressed despite retries, or
has been waiting in a transitional state past a threshold.

Stuck criteria (mirrors ``routers/admin_settlements.py:_stuck_filter``):
- ``FAILED`` or ``ON_HOLD`` with ``retry_count >= MAX_TRANSFER_RETRIES``
- ``PENDING`` older than ``STUCK_PAYOUT_THRESHOLD_HOURS``
- ``TRANSFER_INITIATED`` older than ``STUCK_PAYOUT_THRESHOLD_HOURS``
  (Razorpay webhook never landed)

Alerts are aggregated per franchisee — one Sentry message per
franchisee per tick, not one per entry.
"""
import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from tortoise.expressions import Q

from utils import safe_create_task

logger = logging.getLogger(__name__)


def build_stuck_filter(
    older_than_hours: int, max_transfer_retries: int
) -> Q:
    """Tortoise filter for commission_ledger_entry rows that look stuck.

    Single source of truth shared by the background detector sweep and
    the admin ``GET /api/admin/settlements/stuck`` endpoint. Stuck means
    one of:

    - ``FAILED`` or ``ON_HOLD`` with ``retry_count >= max_transfer_retries``
      (terminal-but-not-acknowledged), or
    - ``PENDING`` older than ``older_than_hours``, or
    - ``TRANSFER_INITIATED`` older than ``older_than_hours``
      (Razorpay webhook never landed).
    """
    from models import SettlementStatusEnum

    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    return (
        Q(
            settlement_status__in=[
                SettlementStatusEnum.FAILED,
                SettlementStatusEnum.ON_HOLD,
            ],
            retry_count__gte=max_transfer_retries,
        )
        | Q(
            settlement_status=SettlementStatusEnum.PENDING,
            created_at__lt=cutoff,
        )
        | Q(
            settlement_status=SettlementStatusEnum.TRANSFER_INITIATED,
            transfer_initiated_at__lt=cutoff,
        )
    )


class StuckPayoutDetector:
    def __init__(
        self,
        interval_seconds: int = 3600,
        threshold_hours: int = 24,
        max_transfer_retries: int = 3,
        alert_cooldown_hours: int = 24,
    ):
        self.interval_seconds = interval_seconds
        self.threshold_hours = threshold_hours
        self.max_transfer_retries = max_transfer_retries
        self.alert_cooldown_hours = alert_cooldown_hours
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        # Per-franchisee dedup: franchisee_id -> (stuck entry-id set, last alert).
        # Suppresses re-alerting an unchanged stuck set every pass; a changed
        # set or an elapsed cooldown re-alerts. In-memory by design — a restart
        # re-alerts once, which is the right behaviour for an ops signal.
        self._alert_state: dict = {}

    async def start(self):
        if self.is_running:
            logger.warning("Stuck-payout detector already running")
            return
        self.is_running = True
        self._task = safe_create_task(self._loop())
        logger.info(
            "✅ Started stuck_payout_detector "
            "(interval=%ds, threshold=%dh)",
            self.interval_seconds, self.threshold_hours,
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
        logger.info("🛑 Stopped stuck_payout_detector")

    async def _loop(self):
        while self.is_running:
            try:
                await self._sweep_once()
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "❌ Error in stuck_payout_detector loop: %s",
                    e, exc_info=True,
                )
                await asyncio.sleep(min(60, self.interval_seconds))

    async def _sweep_once(self) -> int:
        """Run one detection pass. Returns the number of stuck entries
        found."""
        from models import CommissionLedgerEntry

        entries = await CommissionLedgerEntry.filter(
            build_stuck_filter(
                self.threshold_hours, self.max_transfer_retries
            )
        ).all()
        if not entries:
            return 0

        by_franchisee = defaultdict(list)
        for e in entries:
            by_franchisee[e.franchisee_id].append(e)

        now = datetime.now(timezone.utc)
        active = set(by_franchisee)
        for franchisee_id, group in by_franchisee.items():
            if self._should_alert(franchisee_id, group, now):
                self._emit_alert(franchisee_id, group, now)
        # Forget franchisees that are no longer stuck so they re-alert
        # immediately if they become stuck again later.
        self._alert_state = {
            fid: st for fid, st in self._alert_state.items() if fid in active
        }
        return len(entries)

    def _should_alert(self, franchisee_id: int, group: list, now) -> bool:
        """Alert when the stuck set changed since last alert, or the cooldown
        window has elapsed for an unchanged set (periodic still-stuck heartbeat)."""
        entry_ids = frozenset(e.id for e in group)
        prev = self._alert_state.get(franchisee_id)
        if prev is None or prev[0] != entry_ids:
            return True
        elapsed_h = (now - prev[1]).total_seconds() / 3600
        return elapsed_h >= self.alert_cooldown_hours

    def _emit_alert(self, franchisee_id: int, group: list, now) -> None:
        from services.monitoring_service import SentryHelper

        entry_ids = frozenset(e.id for e in group)
        oldest = min(e.created_at for e in group)
        age_hours = max(0, int((now - oldest).total_seconds() // 3600))
        statuses = {
            (e.settlement_status.value if hasattr(e.settlement_status, "value") else str(e.settlement_status))
            for e in group
        }
        SentryHelper.capture_message(
            f"Stuck franchisee payouts: {len(group)} entries for franchisee {franchisee_id}",
            level="warning",
            tags={
                "franchisee_id": franchisee_id,
                "count": len(group),
                "oldest_age_hours": age_hours,
            },
            extra={
                "statuses": sorted(statuses),
                "entry_ids": sorted(entry_ids)[:50],
                "threshold_hours": self.threshold_hours,
            },
        )
        logger.warning(
            "Stuck payouts: franchisee=%d count=%d oldest_age_h=%d statuses=%s",
            franchisee_id, len(group), age_hours, sorted(statuses),
        )
        self._alert_state[franchisee_id] = (entry_ids, now)


_stuck_detector: Optional[StuckPayoutDetector] = None


async def start_stuck_payout_detector():
    """Start the background detector. No-op when
    ``RAZORPAY_ROUTE_ENABLED`` is not "true"."""
    global _stuck_detector

    if os.getenv("RAZORPAY_ROUTE_ENABLED", "false").lower() != "true":
        logger.info(
            "RAZORPAY_ROUTE_ENABLED != true; skipping stuck_payout_detector"
        )
        return

    interval = int(
        os.getenv("STUCK_PAYOUT_CHECK_INTERVAL_SECONDS", "3600")
    )
    threshold = int(os.getenv("STUCK_PAYOUT_THRESHOLD_HOURS", "24"))
    max_retries = int(os.getenv("MAX_TRANSFER_RETRIES", "3"))
    alert_cooldown = int(os.getenv("STUCK_PAYOUT_ALERT_COOLDOWN_HOURS", "24"))

    if _stuck_detector is None:
        _stuck_detector = StuckPayoutDetector(
            interval_seconds=interval,
            threshold_hours=threshold,
            max_transfer_retries=max_retries,
            alert_cooldown_hours=alert_cooldown,
        )
    await _stuck_detector.start()


async def stop_stuck_payout_detector():
    global _stuck_detector
    if _stuck_detector:
        await _stuck_detector.stop()
