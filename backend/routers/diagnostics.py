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
    diagnostic_redaction,
    storage_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostic Bundles"])

BUNDLE_MAGIC = "#VLTDIAG/1"
_HEADER_INT_FIELDS = ("boot", "seq", "first", "last", "overflow")
_BODY_PREVIEW_CHARS = 200

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


def _parse_bundle_header(first_line: str) -> tuple[dict, list[str]]:
    """Parse the `#VLTDIAG/1 boot=.. seq=..` line. Returns (fields, warnings).

    Never rejects: a malformed header still gets archived, because a bundle we
    cannot parse is more useful on disk than discarded.
    """
    tokens = first_line.split()
    if not tokens or tokens[0] != BUNDLE_MAGIC:
        got = tokens[0] if tokens else "<empty>"
        return {}, [f"first line is not a {BUNDLE_MAGIC} header (got {got!r})"]

    fields: dict = {}
    warnings: list[str] = []
    for token in tokens[1:]:
        key, sep, value = token.partition("=")
        if not sep:
            warnings.append(f"malformed header token {token!r}")
            continue
        fields[key] = value

    for name in _HEADER_INT_FIELDS:
        if name not in fields:
            warnings.append(f"header is missing {name}=")
            continue
        try:
            fields[name] = int(fields[name])
        except ValueError:
            warnings.append(f"header field {name}={fields[name]!r} is not an integer")
    return fields, warnings


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


async def _archive(charger_id: str, body: bytes, header: dict) -> str:
    """Persist the bundle to S3 and return its key. Raises on failure.

    Deliberately raises rather than degrading to local disk: the caller turns a
    failure into a 503 so the charger keeps its records and retries. A disk
    fallback here would let a 2xx claim a durability the bundle does not have.
    """
    key = storage_service.build_diagnostic_bundle_s3_key(
        charger_id, datetime.now(timezone.utc), header.get("seq")
    )
    # boto3 is synchronous — keep it off the event loop.
    await asyncio.to_thread(storage_service.upload_diagnostic_bundle_to_s3, key, body)
    return key


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

    lines = text.splitlines()
    header, header_warnings = _parse_bundle_header(lines[0] if lines else "")
    warnings += header_warnings

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

    # Check for a re-send BEFORE archiving. A lost response is the common
    # failure on a cellular link, so a retry must not cost a second S3 object;
    # returning the original key also lets the charger confirm what we hold.
    duplicate = await diagnostic_bundle_service.find_duplicate(charger, header)
    if duplicate is not None:
        logger.info(
            "📟 Re-send of seq=%s epoch=%s from %s — already archived at %s",
            duplicate.bundle_seq, duplicate.epoch,
            charger.charge_point_string_id, duplicate.s3_key,
        )
        return {
            "ok": True,
            "received_bytes": len(raw),
            "line_count": max(len(lines) - 1, 0),
            "header": header,
            "header_valid": not header_warnings,
            "stored_key": duplicate.s3_key,
            "recorded": False,
            "epoch": duplicate.epoch,
            "overflow_delta": duplicate.overflow_delta,
            "gap_records": duplicate.gap_records,
            "indexed_lines": 0,
            "archive_only_lines": 0,
            "warnings": warnings,
        }

    try:
        s3_key = await _archive(charger.charge_point_string_id, body, header)
    except Exception as exc:
        logger.error(
            "📟 ❌ Diagnostic Bundle archive failed for %s: %s",
            charger.charge_point_string_id, exc, exc_info=True,
        )
        # Genuine exception, so it belongs in Sentry rather than a threshold
        # alert: the archive is failing and every charger is being told to
        # retry. Detected loss (overflow/gap) is a *measurement* and stays in
        # New Relic; this is something that threw.
        SentryHelper.capture_exception(exc, extra={
            "charger_id": charger.charge_point_string_id,
            "bundle_seq": header.get("seq"),
            "stage": "s3_archive",
        })
        raise HTTPException(
            status_code=503, detail="Could not archive bundle; retry later"
        ) from exc

    line_count = max(len(lines) - 1, 0)
    bundle, created = await diagnostic_bundle_service.record_bundle(
        charger=charger,
        header=header,
        s3_key=s3_key,
        size_bytes=len(body),
        line_count=line_count,
        header_valid=not header_warnings,
    )

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
    if created:
        safe_create_task(
            asyncio.to_thread(
                diagnostic_fanout.forward_bundle,
                text,
                charger.charge_point_string_id,
                header.get("seq"),
                bundle.epoch if bundle else 0,
            ),
            name=f"diag-fanout-{charger.charge_point_string_id}",
        )

    logger.info(
        "📟 Diagnostic Bundle: charger=%s bytes=%s decoded=%s lines=%s header=%s "
        "s3_key=%s new=%s fanout=%s warnings=%s",
        charger.charge_point_string_id, len(raw), len(body), line_count,
        header or "<none>", s3_key, created, "scheduled" if created else "skipped",
        warnings or "none",
    )

    return {
        "ok": True,
        "received_bytes": len(raw),
        "decoded_bytes": len(body),
        "line_count": line_count,
        "header": header,
        "header_valid": not header_warnings,
        "body_preview": text[:_BODY_PREVIEW_CHARS],
        "stored_key": s3_key,
        # False means this bundle was already recorded — the charger is retrying
        # after a lost response, and may safely advance its delivered marker.
        "recorded": created,
        "epoch": bundle.epoch if bundle else None,
        "overflow_delta": bundle.overflow_delta if bundle else 0,
        "gap_records": bundle.gap_records if bundle else 0,
        "fanout": "scheduled" if created else "skipped",
        "warnings": warnings,
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
    epoch: int
    bundle_seq: int
    boot: Optional[int]
    first_record: Optional[int]
    last_record: Optional[int]
    overflow: Optional[int]
    overflow_delta: int
    gap_records: int
    size_bytes: int
    line_count: int
    header_valid: bool
    received_at_ist: str
    lossy: bool


def _to_summary(bundle) -> BundleSummary:
    from utils import to_ist

    return BundleSummary(
        id=bundle.id,
        charger_id=bundle.charger_id,
        charge_point_string_id=bundle.charger.charge_point_string_id,
        epoch=bundle.epoch,
        bundle_seq=bundle.bundle_seq,
        boot=bundle.boot,
        first_record=bundle.first_record,
        last_record=bundle.last_record,
        overflow=bundle.overflow,
        overflow_delta=bundle.overflow_delta,
        gap_records=bundle.gap_records,
        size_bytes=bundle.size_bytes,
        line_count=bundle.line_count,
        header_valid=bundle.header_valid,
        # Stored UTC, rendered IST — the repo-wide rule for anything a human reads.
        received_at_ist=to_ist(bundle.created_at).isoformat(),
        lossy=bool(bundle.overflow_delta or bundle.gap_records),
    )


@admin_router.get("/chargers/{charger_id}/bundles", response_model=List[BundleSummary])
async def list_charger_bundles(
    charger_id: int,
    limit: int = Query(50, ge=1, le=200),
    admin_user: User = Depends(require_admin()),
):
    """Recent Diagnostic Bundles for one charger, newest first."""
    from models import DiagnosticBundle

    bundles = (
        await DiagnosticBundle.filter(charger_id=charger_id)
        .select_related("charger")
        .order_by("-created_at")
        .limit(limit)
    )
    return [_to_summary(b) for b in bundles]


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
