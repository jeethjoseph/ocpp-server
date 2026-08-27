"""In-band marker parsing for Diagnostic Bundle bodies — ADR 0030.

The charger keeps no state across reboot, so everything the server needs about
a bundle is carried *inside* the body as ordinary log records rather than in a
header of persisted counters. This module owns reading them:

  * ``===== BOOT`` markers, which delimit one boot's records from the next;
  * ``TIME_SYNC boot_ms=<n> utc=<iso>`` lines, which anchor a segment's
    millisecond-since-boot clock to real time;
  * the ESP-IDF / AT console line formats the records themselves use.

**Anchoring is per-segment, and resolves in both directions.** ``boot_ms`` is
monotonic for the life of one boot, so a single anchor fixes the wall-clock time
of every record in that segment — including records written *before* the sync
happened. That is what makes the mechanism survive an outage: a charger that
loses network logs unanchored, reconnects, emits ``TIME_SYNC``, and the whole
preceding segment becomes resolvable. Anchoring *across* segments is never
correct — two anchors in one real bundle disagreed by 73 seconds.

Extracted from ``diagnostic_fanout`` so the ingest path can use it too. The
fan-out is a derived view; loss accounting is not, and it was previously reading
a header instead of the body it is meant to describe.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# ESP-IDF console format: `I (683) TAG: message`
_ESP_LINE_RE = re.compile(r"^([IWEDV])\s*\((\d+)\)\s*([^:]{1,40}):\s*(.*)$")
# AT-command trace: `[     326] TX> AT+QWSCLOSE=0`
_AT_LINE_RE = re.compile(r"^\[\s*(\d+)\]\s*(.*)$")
# Boot marker. Accepts an optional boot counter and degrades to an unnumbered
# marker, which is what shipped firmware actually emits
# (`===== BOOT @278 ms, reset reason 3 =====`).
_BOOT_RE = re.compile(r"=====\s*BOOT\b(?:.*?\bn=(\d+))?", re.IGNORECASE)
# Clock anchor: `TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z`
_TIME_SYNC_RE = re.compile(
    r"TIME_SYNC\s+boot_ms=(\d+)\s+utc=(\d{4}-\d{2}-\d{2}T[\d:]+Z)", re.IGNORECASE
)
# Firmware's older free-text form, kept so bundles from pre-C1 units still anchor.
_TIME_SYNC_LOOSE_RE = re.compile(
    r"Time synced from heartbeat:\s*(\d{4}-\d{2}-\d{2}T[\d:]+Z)", re.IGNORECASE
)
# Ring-wrap event: `DiagUpload: body short by 80 B (ring wrapped mid-upload)`.
# A *recency* signal only — it says wrapping is happening now, not how much has
# been destroyed in total. Cumulative overwrite accounting needs a counter in
# storage separate from the data it describes, which this hardware cannot keep
# (ADR 0030). Do not present a count of these as a total loss figure.
_RING_WRAP_RE = re.compile(r"ring wrapped mid-upload", re.IGNORECASE)

# ESP-IDF prefixes every line with its level. Mapping them to standard names is
# what makes `WHERE severity.text = 'ERROR'` work across the fleet.
_LEVELS = {"I": "INFO", "W": "WARN", "E": "ERROR", "D": "DEBUG", "V": "TRACE"}

# A body may still open with the superseded `#VLTDIAG/1 ...` header line. It is
# no longer read for meaning, but it must be excluded from content hashing: it
# is the only part of a retried bundle that changes between attempts, so hashing
# it in means retries never dedupe (observed: 3 retries, 460 identical body
# lines, 3 different digests, differing only in `last=`).
_LEGACY_HEADER_PREFIX = "#VLTDIAG/"


def strip_legacy_header(text: str) -> str:
    """Drop a leading `#VLTDIAG/...` line if present. Idempotent."""
    if text.startswith(_LEGACY_HEADER_PREFIX):
        _, sep, rest = text.partition("\n")
        return rest if sep else ""
    return text


def content_digest(text: str) -> str:
    """Stable identity for a bundle body: SHA-256 over the records themselves.

    Two rules, both learned the hard way:

    * **The legacy header is excluded.** It is the only part of a retried bundle
      that changes between attempts — three real retries in staging carried 460
      byte-identical body lines and three different digests, differing solely in
      the header's ``last=``. Hashing it in means retries never de-duplicate.
    * **The body is hashed raw, before redaction.** Identity answers "has this
      charger sent me these bytes before", which must not move when *our* policy
      moves. Hashing post-redaction would rotate every historical digest the day
      a redaction pattern is added, making every old retry look new.
    """
    return hashlib.sha256(strip_legacy_header(text).encode("utf-8")).hexdigest()


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


def count_ring_wraps(text: str) -> int:
    """How many ring-wrap events this bundle reports. Recency, not a total."""
    return len(_RING_WRAP_RE.findall(text))


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
        #
        # `boot_ms - anchor_ms` is deliberately signed: a record written BEFORE
        # the clock sync resolves to a time before the anchor. Without that a
        # whole outage segment would collapse onto the moment connectivity
        # returned — precisely the records worth reading.
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


def resolve_window(text: str, received_at: datetime) -> tuple[Optional[datetime], Optional[datetime], bool]:
    """When were this bundle's records actually written?

    Returns ``(first_utc, last_utc, approximate)``.

    ``approximate`` is True when the window cannot be fully trusted — either no
    segment anchored at all (both bounds fall back to ``received_at``, a coarse
    upper bound), or some segments anchored and others did not, so the window is
    derived only from the parts that did. A caller comparing windows between
    consecutive bundles to find a loss gap must not treat an approximate window
    as evidence of anything.
    """
    records, unanchored = resolve_records(text, received_at)
    if not records:
        return None, None, True

    exact = [r["timestamp"] for r in records if not r["time_approx"]]
    if not exact:
        # Nothing anchored. Receipt time is all we have, and it is an upper
        # bound rather than a measurement: the records could be arbitrarily old.
        return received_at, received_at, True
    return min(exact), max(exact), unanchored > 0
