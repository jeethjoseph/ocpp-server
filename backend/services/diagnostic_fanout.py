"""Fan out Diagnostic Bundle lines to New Relic over OTLP — ADR 0029.

One upload produces two artifacts. S3 holds the raw bundle and is the archive of
record; this module turns the same bundle into individual, searchable log lines
so fleet-wide questions ("which chargers show this AT failure?") are answerable
at all. A blob-per-charger archive answers none of them.

**Why OTLP and not the Log API.** Only OTLP synthesizes a New Relic *entity*
from `service.name`, which is what keeps ~48k charger lines/day out of an
application-log stream running ~240k/day. Measured on the account: the same
identity attributes sent to `log-api.newrelic.com` are stored as plain
attributes with `entity.guid: None`.

**Timestamps are reconstructed, not read.** Charger lines carry milliseconds
since boot, and that counter restarts at every reboot — a single bundle can span
several boots. Segments are split on BOOT markers and each is anchored by its own
`TIME_SYNC` line, because anchoring across a bundle produces confidently wrong
times (observed: two anchors in one real bundle disagreed by 73 seconds).

**Nothing here may fail an upload.** The bundle is already durably in S3 by the
time this runs; the search index is a derived view, and a vendor outage must not
make a charger re-send data that is already safe.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# ESP-IDF console format: `I (683) TAG: message`
_ESP_LINE_RE = re.compile(r"^([IWEDV])\s*\((\d+)\)\s*([^:]{1,40}):\s*(.*)$")
# AT-command trace: `[     326] TX> AT+QWSCLOSE=0`
_AT_LINE_RE = re.compile(r"^\[\s*(\d+)\]\s*(.*)$")
# Boot marker. Accepts the boot counter requested in change C1, and degrades to
# an unnumbered marker so older firmware still segments correctly.
_BOOT_RE = re.compile(r"=====\s*BOOT\b(?:.*?\bn=(\d+))?", re.IGNORECASE)
# Clock anchor: `TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z`
_TIME_SYNC_RE = re.compile(
    r"TIME_SYNC\s+boot_ms=(\d+)\s+utc=(\d{4}-\d{2}-\d{2}T[\d:]+Z)", re.IGNORECASE
)
# Firmware's existing free-text form, kept as a fallback so the fan-out works
# before C1 lands: `Time synced from heartbeat: 2026-08-19T12:02:05Z`
_TIME_SYNC_LOOSE_RE = re.compile(
    r"Time synced from heartbeat:\s*(\d{4}-\d{2}-\d{2}T[\d:]+Z)", re.IGNORECASE
)

# ESP-IDF prefixes every line with its level. Mapping them to standard names
# is what makes `WHERE severity.text = 'ERROR'` work across the fleet — without
# it you would be string-matching message bodies to find failures.
# V (Verbose) is included even though current firmware never emits it: if it is
# ever switched on, an unmatched line would silently lose both its level AND its
# millisecond offset, dropping to an approximate timestamp.
_LEVELS = {"I": "INFO", "W": "WARN", "E": "ERROR", "D": "DEBUG", "V": "TRACE"}

# New Relic drops records already older than 48h, silently, returning success.
# Stay clear of the boundary rather than racing it.
_MAX_AGE = timedelta(hours=47)
# The ingest path caps a payload at 1 MB; batch well under it.
_BATCH_SIZE = 400
_OTLP_DEFAULT = "https://otlp.nr-data.net:4318/v1/logs"


def _enabled() -> bool:
    return os.getenv("DIAGNOSTIC_FANOUT_ENABLED", "false").strip().lower() == "true"


def service_name() -> str:
    """Per-environment entity, mirroring how OCPP-Server-{env} already splits."""
    env = os.getenv("ENVIRONMENT", "development").strip().lower()
    suffix = {"production": "Production", "prod": "Production", "staging": "Staging"}.get(
        env, "Development"
    )
    return f"VoltLync-Charger-Logs-{suffix}"


def _parse_line(line: str) -> Optional[dict]:
    """Extract (boot_ms, level, subsystem, message) from one console line."""
    m = _ESP_LINE_RE.match(line)
    if m:
        return {"boot_ms": int(m.group(2)), "level": _LEVELS.get(m.group(1), "INFO"),
                "subsystem": m.group(3).strip(), "message": line}
    m = _AT_LINE_RE.match(line)
    if m:
        # The AT trace's bracketed counter is NOT the ESP-IDF ms-since-boot
        # clock — real bundles show `[326]` sitting between `I (743)` and
        # `I (753)`, so it ticks independently. Using it as an offset would
        # place these lines several hundred ms early. Left untimed instead, so
        # they inherit position from their neighbours, which is accurate to
        # within one log line and never confidently wrong.
        return {"boot_ms": None, "level": "DEBUG",
                "subsystem": "at", "message": line}
    # Unparseable lines are forwarded, not dropped — firmware format drifts, and
    # a silent drop means an update deletes logs with nothing reporting it.
    return {"boot_ms": None, "level": "INFO", "subsystem": "raw", "message": line}


def split_boot_segments(lines: Iterable[str]) -> list[list[str]]:
    """Split a bundle body into per-boot segments on BOOT markers."""
    segments: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _BOOT_RE.search(line):
            if current:
                segments.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        segments.append(current)
    return segments


def find_anchor(segment: Iterable[str]) -> Optional[tuple[int, datetime]]:
    """Find this segment's (boot_ms, utc) clock anchor, if it has one."""
    for line in segment:
        m = _TIME_SYNC_RE.search(line)
        if m:
            utc = datetime.strptime(m.group(2), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return int(m.group(1)), utc
        m = _TIME_SYNC_LOOSE_RE.search(line)
        if m:
            parsed = _parse_line(line)
            if parsed and parsed["boot_ms"] is not None:
                utc = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                return parsed["boot_ms"], utc
    return None


def _fill_missing_timestamps(resolved: list, received_at: datetime) -> None:
    """Give every line a timestamp, in place, rewriting the list as triples.

    Fills forward first (a line inherits the one before it), then backward for
    anything still unset — which is how a segment's leading BOOT marker gets
    placed beside the boot it announces rather than at the upload time.
    """
    n = len(resolved)
    filled: list[Optional[datetime]] = [ts for _, ts in resolved]

    carry = None
    for i in range(n):
        if filled[i] is not None:
            carry = filled[i]
        elif carry is not None:
            filled[i] = carry

    carry = None
    for i in range(n - 1, -1, -1):
        if filled[i] is not None:
            carry = filled[i]
        elif carry is not None:
            filled[i] = carry

    for i in range(n):
        parsed, exact = resolved[i]
        ts = filled[i] if filled[i] is not None else received_at
        resolved[i] = (parsed, ts, exact is None)


def resolve_records(text: str, received_at: datetime) -> tuple[list[dict], int]:
    """Turn a bundle body into timestamped records.

    Returns ``(records, unanchored_segments)``. A segment with no anchor — the
    charger never reached the server that boot — falls back to the upload time
    so its lines stay searchable, flagged ``time_approx`` so nobody reads them
    as precise.
    """
    segments = split_boot_segments(text.splitlines())
    records: list[dict] = []
    unanchored = 0

    for seg_index, segment in enumerate(segments):
        anchor = find_anchor(segment)
        if anchor is None:
            unanchored += 1
        anchor_ms, anchor_utc = anchor if anchor else (None, None)

        # Resolve what we can, then fill the rest from the nearest neighbour.
        # Lines with no parseable offset (BOOT markers, wrapped continuations)
        # must not jump to the upload time — that would scatter them hours from
        # the events they belong to. A BOOT marker in particular *leads* its
        # segment, so filling only backwards would never reach it; the pass below
        # looks forward as well.
        resolved: list[tuple[dict, Optional[datetime]]] = []
        for line in segment:
            if not line.strip():
                continue
            parsed = _parse_line(line)
            ts = None
            if anchor and parsed["boot_ms"] is not None:
                ts = anchor_utc + timedelta(milliseconds=parsed["boot_ms"] - anchor_ms)
            resolved.append((parsed, ts))

        _fill_missing_timestamps(resolved, received_at)

        for parsed, ts, approx in resolved:  # type: ignore[misc]
            records.append({**parsed, "timestamp": ts, "time_approx": approx,
                            "boot_segment": seg_index})
    return records, unanchored


def _within_window(record: dict, now: datetime) -> bool:
    return (now - record["timestamp"]) <= _MAX_AGE


def _to_otlp(records: list[dict], charger_code: str, bundle_seq, epoch) -> dict:
    return {"resourceLogs": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": service_name()}},
            {"key": "deployment.environment",
             "value": {"stringValue": os.getenv("ENVIRONMENT", "development")}},
        ]},
        "scopeLogs": [{"logRecords": [
            {
                "timeUnixNano": str(int(r["timestamp"].timestamp() * 1e9)),
                "severityText": r["level"],
                "body": {"stringValue": r["message"][:4000]},
                "attributes": [
                    {"key": "charger_code", "value": {"stringValue": charger_code}},
                    {"key": "subsystem", "value": {"stringValue": r["subsystem"][:60]}},
                    {"key": "bundle_seq", "value": {"intValue": str(bundle_seq)}},
                    {"key": "epoch", "value": {"intValue": str(epoch)}},
                    {"key": "boot_segment", "value": {"intValue": str(r["boot_segment"])}},
                    {"key": "time_approx", "value": {"boolValue": r["time_approx"]}},
                ],
            } for r in records
        ]}],
    }]}


def _post(payload: dict, license_key: str, endpoint: str) -> int:
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode(),
        headers={"Api-Key": license_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status


def forward_bundle(text: str, charger_code: str, bundle_seq, epoch,
                   received_at: Optional[datetime] = None) -> dict:
    """Forward a bundle's lines. Synchronous — call via ``asyncio.to_thread``.

    Returns a summary dict; never raises. The caller has already archived the
    bundle durably, so a failure here is a degraded search index, not lost data,
    and must not turn into a non-2xx that makes the charger re-send.
    """
    summary = {"forwarded": 0, "too_old": 0, "unanchored_segments": 0, "batches": 0,
               "enabled": _enabled()}
    if not _enabled():
        return summary

    license_key = os.getenv("NEW_RELIC_LICENSE_KEY", "").strip()
    if not license_key:
        logger.warning("📟 Fan-out enabled but NEW_RELIC_LICENSE_KEY is unset — skipping")
        return summary

    now = datetime.now(timezone.utc)
    received_at = received_at or now
    records, unanchored = resolve_records(text, received_at)
    summary["unanchored_segments"] = unanchored

    fresh = [r for r in records if _within_window(r, now)]
    summary["too_old"] = len(records) - len(fresh)

    endpoint = os.getenv("DIAGNOSTIC_FANOUT_OTLP_ENDPOINT", _OTLP_DEFAULT)
    for start in range(0, len(fresh), _BATCH_SIZE):
        batch = fresh[start:start + _BATCH_SIZE]
        try:
            _post(_to_otlp(batch, charger_code, bundle_seq, epoch), license_key, endpoint)
            summary["forwarded"] += len(batch)
            summary["batches"] += 1
        except Exception as exc:
            logger.error("📟 OTLP fan-out batch failed for %s: %s", charger_code, exc)
            # The bundle is already safe in S3, so this degrades search only —
            # but it is still an exception, and silent degradation is how an
            # index quietly stops being complete.
            try:
                from services.monitoring_service import SentryHelper
                SentryHelper.capture_exception(exc, extra={
                    "charger_id": charger_code, "bundle_seq": bundle_seq,
                    "stage": "otlp_fanout", "batch": summary["batches"],
                })
            except Exception:
                pass
            break

    if summary["too_old"]:
        # Visible rather than silent: New Relic would drop these without a word,
        # leaving an index that looks complete and is not.
        logger.warning(
            "📟 %s lines from %s exceeded the 48h ingest window — archive-only (S3 has them)",
            summary["too_old"], charger_code,
        )
    return summary
