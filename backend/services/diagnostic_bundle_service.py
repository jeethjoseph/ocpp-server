"""Diagnostic Bundle ingest bookkeeping — ADR 0029, revised by ADR 0030.

The archive in S3 answers *"what happened?"*. This module answers the question
the archive cannot: *"did we receive everything?"* It owns two concerns that
only make sense across bundles, never within one:

  * **Idempotency** — a charger that retries after a lost response re-sends the
    same bundle; the retry is a no-op, not a second archive. Keyed on the
    content digest, because the firmware reuses sequence numbers across
    genuinely different bundles.
  * **Loss signalling** — a silence window between two bundles means records
    are missing; a ring-wrap event means the charger destroyed records nobody
    received.

**What this module deliberately no longer does.** ADR 0029 tracked a server-held
epoch, a record-range gap and a monotonic overflow delta, all derived from a
bundle header of counters the charger persisted across reboot. The hardware
cannot hold those counters, and every one of the five header fields was wrong in
the field. The cumulative overwrite total in particular is **not recoverable**
and is not approximated here — a ring-wrap event says loss is happening now, not
how much has been lost. See ADR 0030.
"""
from __future__ import annotations

import logging
import os

from tortoise.exceptions import IntegrityError

logger = logging.getLogger(__name__)


async def _previous_bundle(charger_id: int):
    """The charger's most recent bundle by arrival, or None."""
    from models import DiagnosticBundle
    return (
        await DiagnosticBundle.filter(charger_id=charger_id)
        .order_by("-created_at")
        .first()
    )


async def find_duplicate(charger, content_sha256: str):
    """Return an already-recorded bundle with this exact content, or None.

    Lets the caller skip the S3 write entirely on a retry. Archiving first and
    de-duplicating afterwards is correct but wasteful: on a flaky cellular link
    a lost response is the *common* failure, so redundant objects would
    accumulate for every re-send.

    Keyed on content, not sequence (ADR 0030). The firmware reuses a sequence
    number across genuinely different bundles, so a sequence-keyed check treated
    every retry as a reflash — the defect that inflated ``epoch`` to 11 in 15
    bundles and, through it, silently zeroed the loss accounting.
    """
    from models import DiagnosticBundle

    if not content_sha256:
        return None
    # `archived_at__isnull=False` is load-bearing. A row whose S3 write failed
    # is a reservation, not a delivery; matching it here would answer 2xx for
    # records that exist nowhere, which is the one thing the durability gate
    # exists to prevent.
    return await DiagnosticBundle.filter(
        charger_id=charger.id, content_sha256=content_sha256,
        archived_at__isnull=False,
    ).first()


async def reserve_bundle(charger, s3_key: str, size_bytes: int, line_count: int,
                         content_sha256: str, first_utc=None, last_utc=None,
                         time_approximate: bool = False, ring_wrap_events: int = 0):
    """Claim the index row for a bundle *before* its object is written.

    Returns ``(bundle, already_archived)``.

    ``already_archived=True`` means we hold these exact records: the caller
    answers 2xx without writing to S3, which is what makes a retry after a lost
    response cheap.

    ``already_archived=False`` means the caller must now write the object and
    call :func:`mark_archived`. The row may be brand new, or a reservation left
    behind by an earlier attempt whose S3 write failed — in that case it is
    reused rather than duplicated, so a charger retrying into a broken bucket
    accumulates one row, not one per attempt.
    """
    from models import DiagnosticBundle

    existing = await DiagnosticBundle.filter(
        charger_id=charger.id, content_sha256=content_sha256
    ).first()
    if existing is not None:
        if existing.archived_at is not None:
            logger.info(
                "📟 Re-send of %s… from %s — already archived at %s",
                content_sha256[:12], charger.charge_point_string_id, existing.s3_key,
            )
            return existing, True
        logger.info(
            "📟 Resuming an unarchived reservation for %s… from %s",
            content_sha256[:12], charger.charge_point_string_id,
        )
        return existing, False

    try:
        bundle = await DiagnosticBundle.create(
            charger=charger,
            content_sha256=content_sha256,
            first_utc=first_utc,
            last_utc=last_utc,
            time_approximate=time_approximate,
            ring_wrap_events=ring_wrap_events,
            s3_key=s3_key,
            size_bytes=size_bytes,
            line_count=line_count,
        )
    except IntegrityError:
        # Two uploads of the same bundle raced past the lookup above. The unique
        # constraint is the real arbiter; the loser adopts the winner's row
        # rather than surfacing a 500 that would make the charger re-send.
        existing = await DiagnosticBundle.filter(
            charger_id=charger.id, content_sha256=content_sha256
        ).first()
        if existing is None:
            raise
        return existing, existing.archived_at is not None
    return bundle, False


async def mark_archived(bundle, charger=None):
    """Record that the S3 object is durably present. Call only after the put."""
    from datetime import datetime, timezone

    bundle.archived_at = datetime.now(timezone.utc)
    await bundle.save(update_fields=["archived_at"])
    if charger is not None:
        previous = await _previous_archived_before(charger.id, bundle)
        await _emit_loss_signals(charger, bundle, previous)
    return bundle


async def _previous_archived_before(charger_id: int, bundle):
    """The charger's previous *delivered* bundle, for silence measurement."""
    from models import DiagnosticBundle
    return (
        await DiagnosticBundle.filter(
            charger_id=charger_id, archived_at__isnull=False
        )
        .exclude(id=bundle.id)
        .order_by("-created_at")
        .first()
    )


async def stale_reservations(older_than_minutes: int = 60):
    """Rows whose S3 write never completed — the sweep target for issue 06.

    A reservation older than the charger's retry window will not be resumed:
    the charger has moved on, and the row points at an object that was never
    written. Safe to delete, and safe to leave; it is invisible to the duplicate
    check either way.
    """
    from datetime import datetime, timedelta, timezone
    from models import DiagnosticBundle

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    return await DiagnosticBundle.filter(
        archived_at__isnull=True, created_at__lt=cutoff
    )


async def _emit_loss_signals(charger, bundle, previous) -> None:
    """Surface loss as alertable events rather than a row nobody reads.

    Two signals remain, and they are no longer the pair ADR 0029 described.
    A *silence window* says records are missing between two bundles. A *ring
    wrap* says the charger is destroying undelivered records right now. The
    cumulative "how many were destroyed in total" figure is not recoverable
    without cross-reboot persistence and is not approximated here — see ADR 0030.

    Deliberately best-effort: a telemetry failure must never fail an upload that
    was already durably archived.
    """
    try:
        from services.monitoring_service import MetricsCollector

        if bundle.ring_wrap_events:
            logger.warning(
                "📟 %s reported %s ring-wrap event(s) — buffer is destroying "
                "undelivered records",
                charger.charge_point_string_id, bundle.ring_wrap_events,
            )
            MetricsCollector.record_event("DiagnosticBundleRingWrap", {
                "charger_id": charger.charge_point_string_id,
                "ring_wrap_events": bundle.ring_wrap_events,
            })

        gap = _silence_seconds(bundle, previous)
        if gap is not None and gap > _gap_threshold_seconds():
            logger.warning(
                "📟 Silence of %ss for %s between %s and %s — records may be missing",
                gap, charger.charge_point_string_id,
                previous.last_utc, bundle.first_utc,
            )
            MetricsCollector.record_event("DiagnosticBundleSilence", {
                "charger_id": charger.charge_point_string_id,
                "silence_seconds": gap,
            })

        if bundle.time_approximate:
            # Not loss, but the window cannot be used to detect it — worth
            # knowing, because a charger stuck here is invisible to the gap
            # signal entirely.
            logger.info(
                "📟 Bundle from %s has no usable clock anchor; window is approximate",
                charger.charge_point_string_id,
            )
    except Exception as exc:                              # pragma: no cover
        logger.warning("📟 Loss signal emit failed (non-fatal): %s", exc)


def _gap_threshold_seconds() -> int:
    return int(os.getenv("DIAGNOSTIC_GAP_THRESHOLD_SECONDS", "300"))


def _silence_seconds(bundle, previous):
    """Seconds between the previous bundle's end and this one's start.

    None when unknowable. An approximate window on either side makes the
    arithmetic meaningless — receipt time is an upper bound, so a gap measured
    against it would be invented rather than observed.
    """
    if previous is None or bundle.first_utc is None or previous.last_utc is None:
        return None
    if bundle.time_approximate or getattr(previous, "time_approximate", False):
        return None
    gap = (bundle.first_utc - previous.last_utc).total_seconds()
    return int(gap) if gap > 0 else 0
