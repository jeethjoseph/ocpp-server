"""Diagnostic Bundle ingest bookkeeping — ADR 0029.

The archive in S3 answers *"what happened?"*. This module answers the question
the archive cannot: *"did we receive everything?"* It owns three concerns that
only make sense across bundles, never within one:

  * **Idempotency** — a charger that retries after a lost response re-sends the
    same bundle; the retry is a no-op, not a second archive.
  * **Epoch** — a reflash or EEPROM clear sends ``bundle_seq`` back to 1. Under
    a naive unique key the charger's new data would be dropped as duplicate, so
    the server detects the regression and starts a new epoch.
  * **Loss accounting** — a gap in record numbers and a jump in the overflow
    counter mean different things and have opposite remedies, so they are
    tracked separately rather than collapsed into one "missing" number.
"""
from __future__ import annotations

import logging
from typing import Optional

from tortoise.exceptions import IntegrityError

logger = logging.getLogger(__name__)

# The firmware overflow counter is a monotonic uint32; a delta computed across
# its wrap point would otherwise come out hugely negative.
_UINT32 = 1 << 32


async def _previous_bundle(charger_id: int):
    from models import DiagnosticBundle
    return (
        await DiagnosticBundle.filter(charger_id=charger_id)
        .order_by("-epoch", "-bundle_seq")
        .first()
    )


def _is_same_bundle(existing, header: dict) -> bool:
    """Is this the identical bundle we already hold, or a sequence replay?

    Compares the header fields that describe *which records* the bundle covers.
    A charger retrying a lost response re-sends all of them unchanged; a
    reflashed unit reusing sequence numbers will differ in at least one.
    """
    return (
        existing.boot == header.get("boot")
        and existing.first_record == header.get("first")
        and existing.last_record == header.get("last")
    )


def _resolve_epoch(previous, bundle_seq: int) -> tuple[int, bool]:
    """Return (epoch, regressed).

    A ``bundle_seq`` at or below the last one seen means the counter restarted —
    the unit was reflashed or its EEPROM cleared. No firmware-side value can
    prevent this (nothing in the EEPROM survives an EEPROM clear), so the server
    detects it instead. The detector is unambiguous because at one bundle per
    6 hours even a 16-bit counter takes decades to wrap, so any backwards move
    is a genuine reset rather than wraparound.
    """
    if previous is None:
        return 0, False
    if bundle_seq <= previous.bundle_seq:
        return previous.epoch + 1, True
    return previous.epoch, False


def _overflow_delta(previous, overflow: Optional[int], same_epoch: bool) -> int:
    """Records the charger destroyed before delivering them, since last bundle."""
    if overflow is None or previous is None or not same_epoch:
        return 0
    if previous.overflow is None:
        return 0
    delta = overflow - previous.overflow
    if delta < 0:                      # counter wrapped at 2^32
        delta += _UINT32
    return delta


def _gap_records(previous, first_record: Optional[int], same_epoch: bool) -> int:
    """Records missing between the last bundle's end and this one's start."""
    if first_record is None or previous is None or not same_epoch:
        return 0
    if previous.last_record is None:
        return 0
    gap = first_record - (previous.last_record + 1)
    return gap if gap > 0 else 0


async def record_bundle(charger, header: dict, s3_key: str, size_bytes: int,
                        line_count: int, header_valid: bool):
    """Create the index row for an accepted bundle.

    Returns ``(bundle, created)``. ``created=False`` means this exact bundle was
    already recorded — the caller should treat the upload as successful without
    re-archiving, which is what makes a retry after a lost response safe.
    """
    from models import DiagnosticBundle

    bundle_seq = header.get("seq")
    if bundle_seq is None:
        # A header we could not parse still gets archived (the blob is more use
        # on disk than discarded) but cannot participate in sequence tracking.
        return None, True

    previous = await _previous_bundle(charger.id)

    # Duplicate detection MUST run before regression detection, and must compare
    # content rather than sequence alone. Both a retry and a reflash present a
    # bundle_seq at or below the last one seen; only the content tells them
    # apart. A retry re-sends the identical bundle, whereas a reflashed unit
    # reuses sequence numbers for genuinely different records. Deciding on
    # sequence alone made every retry look like a reflash, which defeated the
    # idempotency this exists to provide.
    if previous is not None:
        same_seq = await DiagnosticBundle.filter(
            charger_id=charger.id, epoch=previous.epoch, bundle_seq=bundle_seq
        ).first()
        if same_seq is not None:
            if _is_same_bundle(same_seq, header):
                logger.info(
                    "📟 Duplicate bundle seq=%s epoch=%s from %s — treating as delivered",
                    bundle_seq, same_seq.epoch, charger.charge_point_string_id,
                )
                return same_seq, False
            # Same sequence, different content: the unit was reflashed and is
            # replaying sequence numbers over new records.
            logger.info(
                "📟 seq=%s replayed with different content by %s — new epoch",
                bundle_seq, charger.charge_point_string_id,
            )

    epoch, regressed = _resolve_epoch(previous, bundle_seq)

    same_epoch = previous is not None and not regressed
    overflow = header.get("overflow")
    delta = _overflow_delta(previous, overflow, same_epoch)
    gap = _gap_records(previous, header.get("first"), same_epoch)

    try:
        bundle = await DiagnosticBundle.create(
            charger=charger,
            epoch=epoch,
            bundle_seq=bundle_seq,
            boot=header.get("boot"),
            first_record=header.get("first"),
            last_record=header.get("last"),
            overflow=overflow,
            overflow_delta=delta,
            gap_records=gap,
            s3_key=s3_key,
            size_bytes=size_bytes,
            line_count=line_count,
            header_valid=header_valid,
        )
    except IntegrityError:
        # Two uploads of the same bundle raced: both passed the duplicate check
        # before either inserted. The unique constraint is the real arbiter, so
        # the loser reports the winner's row rather than surfacing a 500 that
        # would make the charger retry something already stored.
        existing = await DiagnosticBundle.filter(
            charger_id=charger.id, epoch=epoch, bundle_seq=bundle_seq
        ).first()
        if existing is not None:
            logger.info(
                "📟 Concurrent upload of seq=%s epoch=%s from %s — keeping the first",
                bundle_seq, epoch, charger.charge_point_string_id,
            )
            return existing, False
        raise

    await _emit_loss_signals(charger, bundle, regressed)
    return bundle, True


async def _emit_loss_signals(charger, bundle, regressed: bool) -> None:
    """Surface loss as alertable events rather than a row nobody reads.

    Deliberately best-effort: a telemetry failure must never fail an upload that
    was already durably archived.
    """
    try:
        from services.monitoring_service import MetricsCollector

        if regressed:
            logger.warning(
                "📟 Sequence regression for %s — new epoch %s (unit reflashed or EEPROM cleared)",
                charger.charge_point_string_id, bundle.epoch,
            )
            MetricsCollector.record_event("DiagnosticBundleEpochReset", {
                "charger_id": charger.charge_point_string_id,
                "epoch": bundle.epoch,
                "bundle_seq": bundle.bundle_seq,
            })

        if bundle.overflow_delta or bundle.gap_records:
            logger.warning(
                "📟 Loss detected for %s: overflow_delta=%s gap_records=%s (seq=%s epoch=%s)",
                charger.charge_point_string_id, bundle.overflow_delta,
                bundle.gap_records, bundle.bundle_seq, bundle.epoch,
            )
            MetricsCollector.record_event("DiagnosticBundleLoss", {
                "charger_id": charger.charge_point_string_id,
                "overflow_delta": bundle.overflow_delta,
                "gap_records": bundle.gap_records,
                # The two causes need different remedies: a gap with no overflow
                # is a lost upload; overflow is the buffer being outrun.
                "cause": "buffer_wrap" if bundle.overflow_delta else "missing_bundle",
                "bundle_seq": bundle.bundle_seq,
                "epoch": bundle.epoch,
            })
    except Exception as exc:
        logger.error("📟 Failed to emit diagnostic loss signal: %s", exc, exc_info=True)


async def find_duplicate(charger, header: dict):
    """Return an already-recorded bundle identical to this one, or None.

    Lets the caller skip the S3 write entirely on a retry. Archiving first and
    de-duplicating afterwards is correct but wasteful: on a flaky cellular link
    a lost response is the *common* failure, so redundant objects would
    accumulate for every re-send.
    """
    from models import DiagnosticBundle

    bundle_seq = header.get("seq")
    if bundle_seq is None:
        return None
    previous = await _previous_bundle(charger.id)
    if previous is None:
        return None
    candidate = await DiagnosticBundle.filter(
        charger_id=charger.id, epoch=previous.epoch, bundle_seq=bundle_seq
    ).first()
    if candidate is not None and _is_same_bundle(candidate, header):
        return candidate
    return None
