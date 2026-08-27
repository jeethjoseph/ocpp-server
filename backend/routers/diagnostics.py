"""Diagnostic Bundle upload — see ADR 0029.

Chargers buffer firmware debug traces in on-board EEPROM and POST them here
periodically over HTTPS, outside the OCPP channel. OCPP `GetDiagnostics` is
deliberately not used.

Two rules shape this module, both guarding failures that are otherwise silent:

  1. **A 2xx means "durably stored".** The response is not sent until the object
     is in S3. A charger advances its delivered marker on 2xx and may then let
     those records be overwritten, so acking before durability would tell it
     data is safe that no longer exists anywhere.

  2. **The Authorization header never reaches a log.** Its password half is the
     Charger Auth Key; leaking it into logs would undo the point of storing only
     a hash. Only the claimed charger identity is ever logged.

Line-level fan-out to New Relic runs after the archive, gated behind
`DIAGNOSTIC_FANOUT_ENABLED`. It is best-effort by design: a failure there
degrades search, never durability.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth_middleware import require_admin
from models import User
from services.monitoring_service import SentryHelper
from utils import safe_create_task

from services import (
    charger_auth_service,
    diagnostic_bundle_service,
    diagnostic_fanout,
    diagnostic_markers,
    diagnostic_redaction,
    storage_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostic Bundles"])


# Per-charger upload rate limit. ADR 0029 sets ~6/hour: enough headroom for the
# 6-hourly schedule plus retries and repeated fault-triggered uploads, tight
# enough to bound a charger stuck in a loop.
# Configurable because the firmware team's bench testing runs far faster than
# the 6-hourly production cadence — pinning the production number would 429
# them mid-test.
_RATE_LIMIT_WINDOW = 3600


def _rate_limit_max() -> int:
    return int(os.getenv("DIAGNOSTIC_BUNDLE_RATE_LIMIT", "6"))
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _enabled() -> bool:
    return os.getenv("DIAGNOSTIC_BUNDLE_ENABLED", "true").strip().lower() == "true"


def _max_bytes() -> int:
    return int(os.getenv("DIAGNOSTIC_BUNDLE_MAX_BYTES", str(2 * 1024 * 1024)))


def _rate_limited_in_process(charger_key: str) -> bool:
    """Fallback limiter, used only when Redis is unreachable.

    Process-local, so it resets on deploy and would multiply across workers.
    Acceptable as a degraded mode — the alternative when Redis is down is no
    limit at all — but never the primary control.
    """
    now = time.time()
    recent = [t for t in _rate_limit_store[charger_key] if t > now - _RATE_LIMIT_WINDOW]
    _rate_limit_store[charger_key] = recent
    if len(recent) >= _rate_limit_max():
        return True
    recent.append(now)
    return False


async def _rate_limited(charger_key: str) -> bool:
    """Fixed-window counter in Redis, shared across workers and containers.

    A counter with a TTL rather than an in-memory list: it survives deploys and
    holds regardless of how many uvicorn workers or backend containers are
    running. The entrypoint currently pins `--workers 1`, which is the only
    reason the in-process version worked at all — that is a config detail, not a
    guarantee, so the real control lives here.
    """
    from redis_manager import redis_manager

    client = getattr(redis_manager, "redis_client", None)
    if client is None:
        return _rate_limited_in_process(charger_key)

    key = f"diag_upload_rate:{charger_key}"
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, _RATE_LIMIT_WINDOW)
        return count > _rate_limit_max()
    except Exception as exc:
        logger.warning("📟 Redis rate-limit check failed (%s); falling back in-process", exc)
        return _rate_limited_in_process(charger_key)


def _decode_body(raw: bytes, content_encoding: Optional[str]) -> tuple[bytes, list[str]]:
    """Gunzip if the charger declared gzip. Returns (decoded, warnings)."""
    if (content_encoding or "").strip().lower() != "gzip":
        return raw, []
    try:
        return gzip.decompress(raw), []
    except Exception as exc:
        return raw, [f"Content-Encoding: gzip declared but body did not decompress ({exc})"]


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=f"Body exceeds {limit} bytes")
    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail=f"Body exceeds {limit} bytes")
    return raw


async def _archive(s3_key: str, body: bytes) -> None:
    """Persist the bundle to S3 at a key already reserved. Raises on failure.

    Deliberately raises rather than degrading to local disk: the caller turns a
    failure into a 503 so the charger keeps its records and retries. A disk
    fallback here would let a 2xx claim a durability the bundle does not have.
    """
    # boto3 is synchronous — keep it off the event loop.
    await asyncio.to_thread(storage_service.upload_diagnostic_bundle_to_s3, s3_key, body)


@router.post("/bundles")
async def receive_bundle(request: Request):
    """Accept an authenticated Diagnostic Bundle and archive it durably."""
    if not _enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    charger = await charger_auth_service.authenticate_charger(
        request.headers.get("authorization")
    )
    if charger is None:
        # Uniform rejection: never distinguishes "unknown charger" from "bad key"
        # from "not provisioned", so the endpoint cannot be used to enumerate ids.
        raise HTTPException(
            status_code=401,
            detail="Invalid charger credentials",
            headers={"WWW-Authenticate": 'Basic realm="diagnostics"'},
        )

    if await _rate_limited(charger.charge_point_string_id):
        raise HTTPException(status_code=429, detail="Too many uploads; retry later")

    raw = await _read_body(request, _max_bytes())
    body, warnings = _decode_body(raw, request.headers.get("content-encoding"))

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
        warnings.append("body is not valid UTF-8 — decoded with replacement characters")

    # Identity, computed on the RAW body before redaction touches it — see
    # `content_digest` for why both the timing and the header exclusion matter.
    content_sha256 = diagnostic_markers.content_digest(text)

    # When these records were actually written. Resolved from the body's own
    # TIME_SYNC anchors, not from a header the charger cannot maintain across a
    # reboot (ADR 0030). Receipt time is the caller's fallback, and is an upper
    # bound rather than a measurement.
    received_at = datetime.now(timezone.utc)
    first_utc, last_utc, time_approximate = diagnostic_markers.resolve_window(
        text, received_at
    )
    ring_wrap_events = diagnostic_markers.count_ring_wraps(text)
    if ring_wrap_events:
        logger.warning(
            "📟 ⚠️  %s reported %s ring-wrap event(s) — the buffer is destroying "
            "undelivered records. Recency signal only, not a total.",
            charger.charge_point_string_id, ring_wrap_events,
        )

    # Redact BEFORE archiving: S3 holds bundles for 90 days, so redacting only
    # on the search-index path would leave the sensitive copy in the archive.
    text, redactions = diagnostic_redaction.redact_bundle(text)
    if diagnostic_redaction.redaction_occurred(redactions):
        warnings.append(f"server-side redaction applied: {redactions}")
        logger.warning(
            "📟 ⚠️  Redacted sensitive content from %s bundle: %s — firmware should "
            "not have emitted this (spec §2.2)",
            charger.charge_point_string_id, redactions,
        )
    body = text.encode("utf-8")

    # Counted after stripping any legacy header line, so a unit mid-rollout does
    # not report one line more than a unit that already dropped it.
    line_count = len(diagnostic_markers.strip_legacy_header(text).splitlines())

    # Index BEFORE archiving, so a failure can never strand an object no row
    # points at — the ordering that produced 195 orphans on staging in one
    # morning, none of which the retention sweep could ever reclaim because it
    # only deletes objects it has rows for.
    #
    # Compensating the other way round — archive, then delete on insert failure
    # — was rejected: it needs an `s3:DeleteObject` grant that ADR 0029
    # deliberately withholds so the application can never remove a bundle.
    s3_key = storage_service.build_diagnostic_bundle_s3_key(
        charger.charge_point_string_id, received_at, content_sha256
    )
    bundle, already_archived = await diagnostic_bundle_service.reserve_bundle(
        charger=charger,
        s3_key=s3_key,
        size_bytes=len(body),
        line_count=line_count,
        content_sha256=content_sha256,
        first_utc=first_utc,
        last_utc=last_utc,
        time_approximate=time_approximate,
        ring_wrap_events=ring_wrap_events,
    )
    if already_archived:
        # A retry after a lost response. Cheap and idempotent: no second object,
        # and the original key lets the charger confirm what we hold.
        return {"ok": True, "recorded": False, "stored_key": bundle.s3_key}

    try:
        await _archive(bundle.s3_key, body)
    except Exception as exc:
        logger.error(
            "📟 ❌ Diagnostic Bundle archive failed for %s: %s",
            charger.charge_point_string_id, exc, exc_info=True,
        )
        # Genuine exception, so it belongs in Sentry rather than a threshold
        # alert: the archive is failing and every charger is being told to
        # retry. Detected loss is a *measurement* and stays in New Relic; this
        # is something that threw.
        SentryHelper.capture_exception(exc, extra={
            "charger_id": charger.charge_point_string_id,
            "content_sha256": content_sha256,
            "stage": "s3_archive",
        })
        # The row stays as an unarchived reservation: invisible to the duplicate
        # check, so the charger is told to re-send rather than being falsely
        # assured, and resumable by the next attempt rather than duplicated.
        raise HTTPException(
            status_code=503, detail="Could not archive bundle; retry later"
        ) from exc

    await diagnostic_bundle_service.mark_archived(bundle, charger)

    # Fan out to the search index only for genuinely new bundles — a retry must
    # not duplicate lines in New Relic. Best-effort by construction: the bundle
    # is already durably archived, so a vendor outage degrades search, never the
    # upload, and must not provoke a re-send of data that is already safe.
    # Scheduled, NOT awaited. A full 192 KB bundle is ~1,600 lines = 5 OTLP
    # batches; awaiting them could add ~100s to the response. The charger is
    # blocked on that 2xx, and if it times out before seeing it, it does not
    # advance its delivered marker and re-sends — the exact failure the
    # durability gate exists to prevent, reintroduced by a derived view that
    # was never allowed to affect the upload.
    safe_create_task(
        asyncio.to_thread(
            diagnostic_fanout.forward_bundle,
            text,
            charger.charge_point_string_id,
            content_sha256,
        ),
        name=f"diag-fanout-{charger.charge_point_string_id}",
    )

    logger.info(
        "📟 Diagnostic Bundle: charger=%s bytes=%s decoded=%s lines=%s "
        "sha=%s window=%s..%s approx=%s wraps=%s s3_key=%s warnings=%s",
        charger.charge_point_string_id, len(raw), len(body), line_count,
        content_sha256[:12], first_utc, last_utc, time_approximate,
        ring_wrap_events, bundle.s3_key, warnings or "none",
    )

    return {
        "ok": True,
        # True: newly archived. The already-held case returned above with False.
        "recorded": True,
        "stored_key": bundle.s3_key,
    }


# ============ Admin surface (ADR 0029) ============
#
# Answers *delivery* questions — did every bundle arrive, and did the charger
# lose anything — and hands back the raw archive. Trace **content** is read in
# New Relic, not here; this is deliberately not a log viewer, and it is not the
# Logs Console (that is a view over the `log` table, ADR 0014).

admin_router = APIRouter(prefix="/api/admin/diagnostics", tags=["Diagnostic Bundles (admin)"])


class BundleSummary(BaseModel):
    id: int
    charger_id: int
    charge_point_string_id: str
    content_sha256: Optional[str]
    size_bytes: int
    line_count: int
    received_at_ist: str
    # When the records were written, per the body's own clock anchors.
    window_start_ist: Optional[str]
    window_end_ist: Optional[str]
    time_approximate: bool
    # Silence between the previous bundle's end and this one's start. Derived at
    # read time, never stored: a delayed bundle can arrive later and fill the
    # hole, and with retries and reboots in play it will. The stored `gap_records`
    # this replaces froze at zero for exactly that kind of reason.
    gap_before_seconds: Optional[int]
    ring_wrap_events: int
    lossy: bool


def _gap_threshold_seconds() -> int:
    """Silence longer than this is treated as a candidate loss window.

    Provisional. The 300 s default derives from one unit during *active* OCPP
    traffic (TIME_SYNC median 20 s, max 212 s). Heartbeat interval is per-charger
    configurable and an idle unit may be far quieter, so the sample is from the
    wrong operating state as well as being small — re-measure across several
    chargers before wiring an alert to it (ADR 0030, "Still open").
    """
    return int(os.getenv("DIAGNOSTIC_GAP_THRESHOLD_SECONDS", "300"))


def _gap_before(bundle, previous) -> Optional[int]:
    """Seconds of silence before this bundle, or None if unknowable.

    An approximate window on *either* side makes the arithmetic meaningless —
    receipt time is an upper bound, so a gap computed against it would be
    invented rather than measured.
    """
    if previous is None or bundle.first_utc is None or previous.last_utc is None:
        return None
    if bundle.time_approximate or previous.time_approximate:
        return None
    gap = (bundle.first_utc - previous.last_utc).total_seconds()
    return int(gap) if gap > 0 else 0


def _to_summary(bundle, previous=None) -> BundleSummary:
    from utils import to_ist

    gap = _gap_before(bundle, previous)
    return BundleSummary(
        id=bundle.id,
        charger_id=bundle.charger_id,
        charge_point_string_id=bundle.charger.charge_point_string_id,
        content_sha256=bundle.content_sha256,
        size_bytes=bundle.size_bytes,
        line_count=bundle.line_count,
        # Stored UTC, rendered IST — the repo-wide rule for anything a human reads.
        received_at_ist=to_ist(bundle.created_at).isoformat(),
        window_start_ist=to_ist(bundle.first_utc).isoformat() if bundle.first_utc else None,
        window_end_ist=to_ist(bundle.last_utc).isoformat() if bundle.last_utc else None,
        time_approximate=bundle.time_approximate,
        gap_before_seconds=gap,
        ring_wrap_events=bundle.ring_wrap_events,
        lossy=bool((gap is not None and gap > _gap_threshold_seconds())
                   or bundle.ring_wrap_events),
    )


@admin_router.get("/chargers/{charger_id}/bundles", response_model=List[BundleSummary])
async def list_charger_bundles(
    charger_id: int,
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin()),
):
    """Recent Diagnostic Bundles for one charger, newest first."""
    from models import DiagnosticBundle

    # One extra row so the oldest bundle in the page still has a predecessor to
    # measure its gap against; without it the last row would always read as
    # having no silence before it.
    bundles = (
        await DiagnosticBundle.filter(charger_id=charger_id)
        .select_related("charger")
        .order_by("-created_at")
        .limit(limit + 1)
    )
    page = bundles[:limit]
    return [
        _to_summary(b, bundles[i + 1] if i + 1 < len(bundles) else None)
        for i, b in enumerate(page)
    ]


@admin_router.get("/bundles/{bundle_id}/download")
async def download_bundle(bundle_id: int, admin_user: User = Depends(require_admin())):
    """Short-lived presigned URL for the raw bundle in S3."""
    from models import DiagnosticBundle

    bundle = await DiagnosticBundle.filter(id=bundle_id).select_related("charger").first()
    if not bundle:
        raise HTTPException(status_code=404, detail="Bundle not found")
    try:
        url = await asyncio.to_thread(
            storage_service.generate_diagnostic_bundle_url, bundle.s3_key
        )
    except Exception as exc:
        logger.error("📟 Presign failed for bundle %s: %s", bundle_id, exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Could not generate download URL") from exc

    logger.info(
        "📟 Admin %s downloaded bundle %s (charger %s)",
        admin_user.id, bundle_id, bundle.charger.charge_point_string_id,
    )
    return {"url": url, "expires_in": 900, "s3_key": bundle.s3_key}
