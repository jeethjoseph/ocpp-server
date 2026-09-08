# Trim the Diagnostic Bundle upload response to a minimal ack

Status: done

## What to build

`POST /api/diagnostics/bundles` currently returns a ~700-byte JSON body including `body_preview` — the first 200 characters of the bundle just uploaded. The charger logs the HTTP response into its ring buffer, so that preview is written back into the very buffer the bundle came from and re-uploaded on the next cycle.

Observed in a real bundle in `voltlync-diagnostics-staging`:

```
I (44694) EC200U: |ecord_count":2346,"header":{"boot":1,"seq":1,"first":589,"last":1612,"overflow":1},
                   "header_valid":true,"body_preview":"#VLTDIAG/1 boot=1 seq=1 first=589 last=1612 overflow=1\n..."
```

This is a self-feeding consumer of the exact resource the feature exists to conserve, and it recurs on every upload.

Cut the response to the minimum the charger needs in order to decide whether to advance its delivered marker:

```json
{"ok": true, "recorded": true, "stored_key": "diagnostics/<cpid>/2026/08/27/20260827T094851Z-a1b2c3d4.txt"}
```

- `ok` — the bundle is durably in S3
- `recorded` — `false` means we already held these exact bytes. Still a success; the charger may advance its delivered marker either way.
- `stored_key` — lets the charger confirm what we hold

Target is under 150 bytes against today's 659-711.

Drop `body_preview`, `header`, `header_valid`, `received_bytes`, `decoded_bytes`, `line_count`, `epoch`, `overflow_delta`, `gap_records`, `warnings`, `fanout`, `indexed_lines`, `archive_only_lines` from the wire response. Keep all of them in the server-side log line — that is where they belong and it already logs them.

Applies to both return paths in `receive_bundle` (the duplicate short-circuit and the normal path). `_BODY_PREVIEW_CHARS` becomes unused and should go.

This is independent of the rest of the header removal and can ship first.

## Acceptance criteria

- [x] Both success responses from `POST /api/diagnostics/bundles` contain only `ok`, `recorded`, `stored_key`.
- [x] Response body is under 150 bytes for a typical bundle (nginx currently logs 659-711).
- [x] The existing server-side `📟 Diagnostic Bundle: ...` log line still records byte counts, line count, header state and warnings.
- [x] `_BODY_PREVIEW_CHARS` and any now-dead preview code removed.
- [x] `docker exec ocpp-backend pytest tests/test_diagnostics_endpoint.py` passes (baseline: 63 passed across the five diagnostics files) (update assertions that read the dropped fields).

## Blocked by

- None — can start immediately

## Comments

**2026-08-27 — implemented.**

- `backend/routers/diagnostics.py` — both return paths cut to `{ok, recorded, stored_key}`; `_BODY_PREVIEW_CHARS` removed. The `📟 Diagnostic Bundle: ...` log line is unchanged and still carries byte counts, line count, header state and warnings.
- `backend/tests/test_diagnostics_endpoint.py` — five tests re-pointed rather than deleted, since each asserted a real behaviour that simply moved:
  - `test_header_is_parsed_and_lines_counted` → `test_response_is_a_minimal_ack` (asserts the exact key set and a <150 byte response)
  - `test_malformed_header_is_archived_anyway` → asserts the S3 write happened, which was always the point
  - `test_gzip_body_is_decompressed_and_stored_decoded` → keeps the decoded-bytes-reach-S3 assertion, drops the response byte counts
  - `test_loss_counters_are_returned_to_the_charger` → `test_loss_counters_are_not_returned_to_the_charger`, inverted deliberately: the charger cannot act on them, its only decision is whether to advance the delivered marker
  - `test_sensitive_content_is_redacted_before_it_reaches_s3` → keeps both S3 assertions, drops the `warnings` echo

Verification: `pytest` across all six diagnostics files — **77 passed**.

Note: the response-shape assertions here now also pin C7 in the firmware change doc — if the response grows again, `test_response_is_a_minimal_ack` fails.

**2026-09-08 — reconciled to `done` by tracker audit.** Every acceptance criterion was already ticked in this file; only the `Status:` line was never flipped, so the issue still advertised itself as available work. Hand-verified rather than grep-scored, per `.scratch/tracker-reconciliation/REPORT.md`: `diagnostics.py:296` returns exactly `{ok, recorded, stored_key}`; `_BODY_PREVIEW_CHARS` absent from the repo.
