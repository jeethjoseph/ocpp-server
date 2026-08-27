# Loss accounting becomes a UTC window derived from in-band TIME_SYNC anchors

Status: ready-for-agent

## What to build

`gap_records` and `overflow_delta` are derived from header record numbers and a persisted overflow counter. Neither survives the firmware's inability to keep state across reboot, and both are currently returning `0` for a different reason — the epoch-inflation bug gates them behind `same_epoch`, which suppressed 19,165 records of reported loss on 2026-08-27.

Replace with a time window resolved from the body.

- Add `first_utc` and `last_utc` (`DatetimeField(null=True)`) to `DiagnosticBundle`, populated from `diagnostic_markers.resolve_window(text)` (issue 02). Null when the body carries no resolvable anchor — that is a real state, not an error, and must not block ingest.
- **Fall back to server receipt time as a coarse upper bound** when no anchor resolves, and flag the row as approximate. All clock anchors come from the network (`src=Heartbeat`, `src=BootNotification`) and there is no RTC, so a boot that never achieves network is entirely unanchorable — and modem registration failure is one of the conditions this feature exists to diagnose. An unanchored bundle must still land somewhere on a timeline rather than vanishing from every time-ordered view.
- A **loss window** is the interval between the previous bundle's `last_utc` and this bundle's `first_utc`, where "previous" is the charger's most recent bundle by `last_utc`. Expose it on the admin surface; do not store a derived gap column.
- Threshold for calling a window a real gap: start at 300 s and make it configurable. **Treat this number as provisional.** It derives from one unit during *active* OCPP traffic (median 20 s, max 212 s). Heartbeat interval is per-charger configurable and an idle unit overnight may be far quieter, so the sample is from the wrong operating state as well as being small. Re-measure across several chargers in both busy and idle periods before wiring any alert to it, and record the basis in ADR 0030's "Still open".
- Keep emitting a loss signal, but on the window rather than a record count. `_emit_loss_signals` changes shape; the New Relic threshold conditions it feeds should follow.

`BundleSummary` on the admin list endpoint becomes:

```
id, charger_id, charge_point_string_id      unchanged
size_bytes, line_count                       unchanged
received_at_ist                              unchanged
content_sha256                               new (issue 03)
window_start_ist, window_end_ist             new — first_utc/last_utc rendered IST, null if unanchored
time_approximate                             new — true when falling back to receipt time
gap_before_seconds                           new — window to the previous bundle, null for the first
ring_wrap_events                             new — count of in-band wrap lines in this bundle
lossy                                        redefined: gap_before_seconds > threshold OR ring_wrap_events > 0
```

Removed by issue 05, not here: `epoch`, `bundle_seq`, `boot`, `first_record`, `last_record`, `overflow_delta`, `gap_records`, `header_valid`.

Timestamps follow the repo rule — stored UTC, rendered IST at the edge, field names suffixed `_ist` (CLAUDE.md "Timestamps"). `received_at_ist` is the existing precedent.

Overwrite loss keeps its own signal: the firmware already logs `DiagUpload: body short by N B (ring wrapped mid-upload) — padding`. Count those lines per bundle and surface the count. That is an in-band record, so it needs no persistence and no header.

## Acceptance criteria

- [x] `first_utc` / `last_utc` added via an Aerich-generated migration, nullable.
- [x] Both populated from per-segment anchors for a multi-boot bundle; null (not an error, not a 500) when no anchor is present.
- [x] Unanchored bundle falls back to receipt time, is flagged approximate, and still appears in time-ordered admin views.
- [x] Admin bundle list returns the loss window between consecutive bundles for a charger.
- [x] Gap threshold configurable via env var, defaulting to 300 s, and documented in `.env.example` plus all three compose files' `backend.environment:` per the CLAUDE.md env-var checklist.
- [x] Ring-wrap lines counted per bundle and surfaced.
- [x] Tests cover: no anchor, single boot, multi-boot, a genuine gap over threshold, jitter under threshold.
- [x] `docker exec ocpp-backend pytest tests/test_diagnostic_bundle_service.py tests/test_diagnostics_endpoint.py` passes (baseline: 63 passed across the five diagnostics files).

## Blocked by

- Issue 02 (needs `diagnostic_markers.resolve_window`)

## Comments

**2026-08-27 — implemented.** Migration `54_20260827121240_diagnostic_bundle_time_window`.

- `models.DiagnosticBundle` — `first_utc`, `last_utc`, `time_approximate`, `ring_wrap_events`.
- `diagnostic_markers.resolve_window()` / `count_ring_wraps()`, populated pre-redaction in the router.
- `routers/diagnostics._gap_before()` / `_gap_threshold_seconds()`; `BundleSummary` reshaped to the schema in this issue. The list endpoint fetches `limit + 1` so the oldest row on a page still has a predecessor to measure against.
- `DIAGNOSTIC_GAP_THRESHOLD_SECONDS` added to all three compose files' `backend.environment:` and to `.env.staging.example` / `.env.prod.example`. Neither dev env file carries any `DIAGNOSTIC_*` var — the convention for these is compose defaults only — so no dev entry was added. Verified in-container: `DIAGNOSTIC_GAP_THRESHOLD_SECONDS=300`.

The receipt-time fallback this issue asked for already existed in `resolve_records` as `time_approx`; it is now surfaced on the row and explicitly tested.

`_gap_before` returns **None, not 0**, when either side is approximate. A gap measured against receipt time would be invented rather than observed — receipt time is an upper bound and the records could be arbitrarily old. Suite: **92 passed**.
