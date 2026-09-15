# Drop the superseded header columns after a soak period

Status: done

## ELI5

Nine database columns stopped being filled in a while back, but we deliberately left them
in place — like keeping a blank field on a form rather than deleting it, so we could go back
if the replacement turned out worse. The replacement has now been checked against real traffic
and it holds up. This deletes them for good.

The catch: the admin screen still reads six of them. Dropping the columns without fixing the
screen first turns "nothing to report" into "undefined missing" in front of an operator.

## What to build

The contract half of the expand/contract in issue 05. Issue 05 stops writing `epoch`, `bundle_seq`, `boot`, `first_record`, `last_record`, `overflow_delta`, `gap_records` and `header_valid` and makes them nullable; this issue removes them.

Deliberately separate and deliberately later. Dropping in the same migration would destroy the historical values with no way back if the replacement underperforms in the field — and this feature has already been wrong once about what it could rely on. The columns cost nothing to keep for a release.

**Entry condition — do not start until all of these hold:**

1. Issue 05 has been live on staging for at least one full upload cycle across a reboot.
2. `first_utc` / `last_utc` are populating for real traffic, including at least one multi-boot bundle and one unanchored bundle.
3. The UTC window has been observed producing a plausible loss signal on real traffic — not merely populating, but agreeing with something independently known (a reboot, a known outage, a wrap event).

Generate the migration with Aerich. **Never hand-edit a past migration to remove these columns** — the `aerich.content` snapshot stays poisoned and every future `aerich migrate` re-emits the cleanup as an unrelated ALTER.

## Acceptance criteria

- [x] All three entry conditions verified and recorded in this issue's Comments before any code is written.
- [x] Aerich-generated migration drops the superseded columns.
- [x] `aerich upgrade` then `aerich downgrade` run clean locally.
- [x] No code references the dropped columns outside migrations and ADRs.
- [x] `docker exec ocpp-backend pytest tests/test_diagnostics_endpoint.py tests/test_diagnostic_bundle_service.py tests/test_diagnostic_fanout.py tests/test_diagnostic_redaction.py tests/test_charger_auth_service.py` passes (baseline: 63 passed across the five diagnostics files).

## Blocked by

- Issue 05, plus the soak period and the scope decision above

## Comments

**2026-08-27 — entry conditions verified against live staging traffic.**

**1. Live across a reboot.** ✅ ADR 0030 deployed 12:56 UTC. 8 `===== BOOT` markers observed across received bundles, several in post-deploy ones.

**2. Windows populating, multi-boot and unanchored both present.** ✅ 15 indexed rows, every one carrying `first_utc`/`last_utc`. Multi-boot bundles present; `time_approximate=true` on four (ids 20, 28, 31 and later), so the unanchored path is exercised on real data, not just fixtures.

**3. The window agrees with something independently known.** ✅ This is the one that mattered, and the correlation is clean. Every silence gap is immediately preceded by a bundle containing an **unanchored** BOOT segment:

```
window               approx   silence  BOOT segments
12:40:12→12:40:29    APPROX            [unanchored]
12:41:12→12:42:00      -       42s
12:54:01→12:55:40    APPROX            [unanchored]
12:56:23→12:58:59      -       42s     [12:57:47]
13:02:11→13:04:22    APPROX            [unanchored]
13:05:02→13:07:32    APPROX    39s     [unanchored]
13:08:12→13:09:38      -       40s
```

The charger reboots, logs a segment with no network and therefore no `TIME_SYNC`, and the ~40 s hole is the reboot itself. Bundles whose BOOT *is* anchored (12:43:47, 12:53:58, 12:57:47) show no gap at all — the unit recovered its clock inside the same window and the trace stayed continuous.

Two things this confirms at once: the reconstructed timeline tracks reality to the second, and `_gap_before` correctly returns **None** rather than a number when either side is approximate — so a reboot is never reported as missing records. That guard was written from reasoning; this is the first evidence it behaves right on real data.

**Honest limitation.** What has been demonstrated is a correct *true negative* — the mechanism declining to cry loss over a reboot. No genuine loss has occurred to produce a true positive: `ring_wrap_events` is 0 on every bundle and no unexplained silence has appeared. That is good news about the fleet rather than a gap in the design, but it does mean the alerting threshold remains unvalidated against a real incident.

Proceeding to drop the columns.

**2026-09-08 — audit: in flight, two defects open.** The backend half is uncommitted in the
working tree — `models.py` drops the nine fields and Aerich generated
`57_20260827131322_diagnostic_bundle_drop_header_columns.py` (upgrade + downgrade both present).
Two acceptance criteria are **not** met:

1. **"No code references the dropped columns."** `frontend/components/DiagnosticBundles.tsx`
   still reads six of them and is unmodified — `epoch` (147, 149), `bundle_seq` (152),
   `first_record`/`last_record` (155), `overflow_delta` (166–167), `gap_records` (168).
   `frontend/lib/api-services.ts:1088` still declares `epoch: number`. Line 168 is the harmful
   one: `undefined > 0` is false, so the table renders **"undefined missing"** — an invented
   loss signal. Issue 11 is the fix; **09 and 11 should land together**, and 09 alone is a
   user-visible regression on the feature's own headline claim.
2. **Dead comment.** `models.py` ~557 keeps the four-line "Superseded by the content digest
   (ADR 0030) … Kept for now so historical values survive" block that described the deleted
   fields, now followed by two blank lines and orphaned.

`aerich upgrade`/`downgrade` and the five-file pytest baseline remain unverified.

**2026-09-08 — both defects fixed; verified end to end.**

Defect 2 (dead comment) removed from `models.py`. Defect 1 fixed by implementing issue 11
— see that issue. Correction to the note above: the frontend was **already** broken in
production, not about to be. `routers/diagnostics.py` is committed (`e9e65a3`) and its
`BundleSummary` stopped returning the header fields at issue 05, so the table has been
rendering `undefined missing` on lossy rows since then. This migration changed nothing for
the UI; it only removed columns the API had stopped serving.

Verification (local, containers up):

```
migration round-trip   downgrade → 9 columns restored
                       upgrade   → 12-column post-drop schema, head at 57
snapshot health        aerich migrate → "No changes detected" (not poisoned)
backend suite          63 passed   (baseline: 63 across the five diagnostics files)
frontend lint          0 errors, 7 warnings (CLAUDE.md baseline; none in changed files)
frontend build         succeeded
```
