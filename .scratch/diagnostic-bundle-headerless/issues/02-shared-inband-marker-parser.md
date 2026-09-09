# Extract the in-band marker parser out of the fan-out into a shared module

Status: done

## What to build

`services/diagnostic_fanout.py` already parses the three in-band markers this design depends on, and does it correctly:

```python
_BOOT_RE      = re.compile(r"=====\s*BOOT\b(?:.*?\bn=(\d+))?", re.IGNORECASE)
_TIME_SYNC_RE = re.compile(r"TIME_SYNC\s+boot_ms=(\d+)\s+utc=(\d{4}-\d{2}-\d{2}T[\d:]+Z)", re.IGNORECASE)
_TIME_SYNC_LOOSE_RE = re.compile(r"Time synced from heartbeat:\s*(\d{4}-\d{2}-\d{2}T[\d:]+Z)", re.IGNORECASE)
```

The problem is placement, not correctness: this runs on the derived New Relic view, while the ingest path — which does the loss accounting — ignores it and trusts the header instead.

Extract into `services/diagnostic_markers.py`, consumed by both the fan-out and (in issues 03-05) the ingest path. Move the ESP-IDF / AT line regexes and `_LEVELS` with it, since segmentation needs them.

Public surface, roughly:

- `parse_segments(text) -> list[Segment]` — splits on BOOT markers; each `Segment` carries its own `TIME_SYNC` anchor(s), its `boot_ms` range, and its lines.
- `resolve_window(text) -> tuple[datetime | None, datetime | None]` — earliest and latest absolute UTC resolvable across all segments, or `(None, None)` when no anchor exists.

Anchoring **must** stay per-segment. The fan-out docstring records why: two anchors in one real bundle disagreed by 73 seconds, so anchoring across a bundle produces confidently wrong times.

Anchoring **must also resolve retroactively within a boot**. `boot_ms` is monotonic for the life of a boot, so one `TIME_SYNC` fixes the wall-clock time of every record in that segment — including records written *before* the sync happened. This is what makes the mechanism survive an outage: a charger that loses network logs unanchored, reconnects, emits `TIME_SYNC`, and the whole preceding segment becomes resolvable. Resolve in both directions from the anchor, not forward only. All observed anchors come from the network (`src=Heartbeat` ×33, `src=BootNotification` ×3) and there is no RTC, so forward-only resolution would throw away the majority of an outage segment.

Pure refactor. No behaviour change to the fan-out, which is the point — its existing tests are the safety net.

## Acceptance criteria

- [x] `services/diagnostic_markers.py` exists and owns the BOOT / TIME_SYNC / ESP-IDF / AT regexes and `_LEVELS`.
- [x] `services/diagnostic_fanout.py` imports from it and defines none of them itself.
- [x] `split_boot_segments` splits the real 196 KB staging bundle on its 3 BOOT markers (yielding 4 segments — content precedes the first marker).
- [x] `resolve_window` returns the correct first/last UTC for that bundle and `(None, None)` for a body with no anchor.
- [x] Per-segment anchoring preserved — a bundle spanning two boots resolves each segment against its own `TIME_SYNC`, never a bundle-wide one.
- [x] Records **preceding** the `TIME_SYNC` line within the same segment resolve correctly (retroactive anchoring), covered by an explicit test.
- [x] Unit tests over fixture bodies covering: no anchor, loose-form anchor only, multi-boot, anchor before first BOOT, and anchor arriving late in a segment.
- [x] `docker exec ocpp-backend pytest tests/test_diagnostic_fanout.py tests/test_diagnostic_markers.py` and any fan-out tests still pass.

## Blocked by

- None — can start immediately

## Comments

**2026-08-27 — implemented.**

- `backend/services/diagnostic_markers.py` — new. Owns `_ESP_LINE_RE`, `_AT_LINE_RE`, `_BOOT_RE`, `_TIME_SYNC_RE`, `_TIME_SYNC_LOOSE_RE`, `_RING_WRAP_RE`, `_LEVELS`, `_parse_line`, `split_boot_segments`, `find_anchor`, `_fill_missing_timestamps`, `resolve_records`. New: `resolve_window`, `strip_legacy_header`, `count_ring_wraps`.
- `backend/services/diagnostic_fanout.py` — 300 → 169 lines; imports and re-exports via `__all__` so existing callers and tests are untouched.
- `backend/tests/test_diagnostic_markers.py` — 14 tests.

Retroactive anchoring turned out to be **already implemented** in `resolve_records` (`boot_ms - anchor_ms` is signed, and `_fill_missing_timestamps` fills forward then backward). The receipt-time fallback issue 04 asks for also already existed as `time_approx`. Both are now covered by explicit tests rather than being incidental.

Verification:
- `pytest` across all six diagnostics files — **77 passed** (63 baseline + 14 new), no behaviour change to the fan-out.
- Against real staging bundles: the 196 KB Aug-21 bundle parses to 4 segments / 2,697 records / 4 ring-wrap events, fully anchored, window 06:06:41.899 → 06:22:16.986 (15.6 min). The window **starts before that bundle's first `TIME_SYNC` at 06:06:53**, confirming retroactive anchoring on production data. The 33 KB Aug-27 bundle: 1 segment, 128 records, 0.7 min — matching an independent measurement of its `boot_ms` span (39.6 s).

**2026-09-08 — reconciled to `done` by tracker audit.** Every acceptance criterion was already ticked in this file; only the `Status:` line was never flipped, so the issue still advertised itself as available work. Hand-verified rather than grep-scored, per `.scratch/tracker-reconciliation/REPORT.md`: `backend/services/diagnostic_markers.py` and `backend/tests/test_diagnostic_markers.py` both exist; `diagnostic_fanout.py` imports from the module rather than defining the regexes.
