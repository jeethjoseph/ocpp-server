# Stop parsing the bundle header and drop the seven header-derived columns

Status: ready-for-agent

## What to build

The removal itself. With identity on a content hash (03) and loss on a UTC window (04), nothing downstream still reads the header, so it can go.

**Ingest** — `routers/diagnostics.py`:
- Delete `_parse_bundle_header`, `_HEADER_INT_FIELDS`, `BUNDLE_MAGIC` and the `header` plumbing through `receive_bundle`.
- `_archive` currently derives the S3 key partly from `header.get("seq")` (`storage_service.build_diagnostic_bundle_s3_key`). Re-key on the upload timestamp plus a short hash prefix. Existing objects keep their old keys — the column stores the key, so historical rows stay resolvable.
- A body whose first line is no longer `#VLTDIAG/1 ...` is just a body. Nothing special happens; there is no header to be valid or invalid.

**Service** — `services/diagnostic_bundle_service.py`: delete `_resolve_epoch`, `_is_same_bundle`, `_overflow_delta`, `_gap_records`, `_previous_bundle`'s epoch/seq ordering, and `_UINT32`. Roughly half the module. Its docstring stays accurate — the module still answers "did we receive everything?", it just does it from the body.

**Schema — expand/contract, and this issue is only the expand half.** Stop *writing* the superseded columns and make them nullable; drop the old unique constraint `uid_diagnostic__charger_7db1f0` since identity now lives on the content hash. **Do not drop the columns here** — issue 09 does that after a soak period. Dropping immediately destroys the historical values with no way back if the UTC window underperforms, and re-adding a column carries the Aerich snapshot risk this repo has been bitten by before.

Keep `header_valid`? No — the concept is replaced. What matters now is whether the body yielded a resolvable time anchor, which issue 04's nullable `first_utc` already expresses. Stop writing it here; issue 09 drops it.

**Do not hand-edit a past migration to remove these columns.** Generate a new one via Aerich — editing an applied migration leaves the `aerich.content` snapshot poisoned and every future `aerich migrate` re-emits the cleanup as an unrelated ALTER.

**This is the relief point.** Removing the header parse is what stops the 500 loop — issues 01, 02, 03 and 06 do not. If an outage needs ending quickly, this issue's ingest change can be taken on its own, ahead of 03 and 04, since it removes the int32 write surface entirely. That is why no BigInt widening ships as an interim fix.

## Acceptance criteria

- [x] No reference to `BUNDLE_MAGIC`, `#VLTDIAG`, `bundle_seq`, `epoch`, `first_record`, `last_record`, `overflow_delta`, `gap_records` remains outside migrations and the ADRs.
- [x] A body with no header line is accepted, archived and indexed normally.
- [x] A body still carrying a legacy `#VLTDIAG/1` first line is accepted and treated as an ordinary record — no special-casing, no warning.
- [x] Aerich-generated migration makes the seven columns nullable and drops the old unique constraint; the columns themselves remain. `aerich upgrade` then `aerich downgrade` both run clean locally.
- [x] Existing rows retain their historical header values — verify by row count and spot-check after migrating.
- [x] `overflow` handling decided from issue 04's ring-wrap results and the decision recorded in ADR 0030's "Still open".
- [x] `docker exec ocpp-backend pytest tests/test_diagnostics_endpoint.py tests/test_diagnostic_bundle_service.py tests/test_diagnostic_fanout.py tests/test_diagnostic_redaction.py tests/test_charger_auth_service.py` passes (baseline: 63 passed across the five diagnostics files).

## Blocked by

- Issue 03 (identity must not depend on seq before seq is removed)
- Issue 04 (loss accounting must not depend on record numbers before they are removed)

Both dependencies apply to the *full* issue. The ingest-side header removal alone has no dependencies and can be taken first as an outage fix.

## Comments

**2026-08-27 — implemented (expand half only).** Migration `55_20260827121723_diagnostic_bundle_retire_header_columns`.

- `routers/diagnostics` — `_parse_bundle_header`, `_HEADER_INT_FIELDS`, `BUNDLE_MAGIC` deleted. `line_count` now counts the records after stripping any legacy header, so a unit mid-rollout doesn't report one line more than one that already dropped it.
- `services/diagnostic_bundle_service` — `_resolve_epoch`, `_is_same_bundle`, `_overflow_delta`, `_gap_records`, `_UINT32` deleted; `record_bundle` keyed purely on the digest. Module docstring rewritten to say plainly what is no longer recoverable.
- `services/storage_service.build_diagnostic_bundle_s3_key` — suffix is the digest, not `-seqN`. Path-traversal guard re-verified.
- `services/diagnostic_fanout` — OTLP attribute `bundle_sha` replaces `bundle_seq` + `epoch`.
- Migration drops the old unique constraint and makes the seven columns nullable. **Columns retained** — issue 09 drops them after a soak.

**A regression was caught by an existing test.** Moving the duplicate check into `record_bundle` put it *after* the S3 write, so every retry would have cost a PUT — and since the key embeds the receipt timestamp, a new object each time rather than an overwrite. That is precisely how 77 orphans accumulated on staging. The pre-archive check is restored, with a comment recording why it must stay ahead of `_archive`.

15 obsolete tests removed and replaced with a tombstone recording where each intent went — and noting the one with **no** replacement: the gap-vs-overflow distinction, ADR 0029's sharpest idea, which needs a counter this hardware cannot keep.

Suite: **77 passed** (92 − 15 obsolete).

**End-to-end against real staging bundles:**

```
big (196KB Aug21)  HTTP 200  138B resp  2698 lines  4 wraps
                   window 06:06:41.899 .. 06:22:16.986  approx=False
retry1 / retry2    identical digest 6ee0f65a2ddd, 459 lines, 2 wraps
response keys      ['ok', 'recorded', 'stored_key']
```
