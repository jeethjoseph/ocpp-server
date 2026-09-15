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
times (observed: two anchors in one real bundle disagreed by 73 seconds). That
parsing now lives in `services/diagnostic_markers`, because the ingest path
needs the same markers for loss accounting — see ADR 0030.

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
from typing import Optional

from services.diagnostic_markers import (
    _LEVELS,
    _parse_line,
    find_anchor,
    resolve_records,
    split_boot_segments,
)

# Re-exported so existing callers and tests keep importing these from here. The
# parsing itself lives in `diagnostic_markers` because the ingest path needs it
# too — see ADR 0030.
__all__ = [
    "forward_bundle", "service_name",
    "split_boot_segments", "find_anchor", "resolve_records", "_parse_line", "_LEVELS",
]

logger = logging.getLogger(__name__)

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


def _within_window(record: dict, now: datetime) -> bool:
    return (now - record["timestamp"]) <= _MAX_AGE


def _to_otlp(records: list[dict], charger_code: str, content_sha256) -> dict:
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
                    # Identifies the bundle a line came from. Was `bundle_seq`
                    # + `epoch`; the firmware reused sequence numbers, so those
                    # attributes pointed at several different bundles at once.
                    {"key": "bundle_sha", "value": {"stringValue": str(content_sha256 or "")[:16]}},
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


def forward_bundle(text: str, charger_code: str, content_sha256=None,
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
            _post(_to_otlp(batch, charger_code, content_sha256), license_key, endpoint)
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
                    "charger_id": charger_code, "content_sha256": content_sha256,
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
