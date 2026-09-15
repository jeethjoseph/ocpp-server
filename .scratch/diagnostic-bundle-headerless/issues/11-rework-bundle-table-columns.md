# Rework the Diagnostic Bundles table around the UTC window

Status: done

## ELI5

The bundle table on the charger page has columns that are now always blank or always `?–?`,
and one that reports records "missing" when they were deliberately abolished rather than lost.

That is worse than an empty column. It invents a data-loss alarm on the one feature whose
entire job is honest loss accounting — so the screen actively undermines the thing it exists
to report. Replace those columns with the UTC window we actually compute now, and say plainly
when that window is approximate.

## What to build

The bundles table on the charger detail page still has **Seq** and **Records** columns
from the pre-ADR-0030 header. Issue 05 stopped writing `bundle_seq`, `first_record` and
`last_record`, so Seq now renders empty on every row and Records renders `?–?` on every
row. Two of the five columns carry no information at all, and one of them advertises
missing data that is not missing — it was deliberately abolished.

Replace them with what actually replaced them: the **UTC window** the bundle covers
(`first_utc` / `last_utc`), and an honest indication when that window is
`time_approximate` — a bundle whose segments could not be anchored to a real clock. An
approximate window is a legitimate state under ADR 0030, not a defect, and the UI
should say so rather than hiding it or implying precision it does not have.

Keep the **Loss** column. It is the one signal that survived the header removal intact
and it is the reason this table exists.

**Sequencing:** this must land *before* issue 09 drops the columns. If the columns go
first, the table reads `undefined` instead of blank. Doing it in this order also means
the UI stops depending on those fields before the migration removes them, which is what
issue 09's "no code references the dropped columns" criterion needs.

## Acceptance criteria

- [ ] Seq and Records columns are gone from the table.
- [ ] The covered UTC window is shown per bundle, rendered in **IST** per the timestamp convention in CLAUDE.md, and labelled so the zone is unambiguous.
- [ ] A bundle with `time_approximate` is visually distinguishable from one with a clock-anchored window, and the distinction is explained in the UI rather than assumed.
- [ ] The Loss column and the download action are unchanged.
- [ ] A bundle whose window is null renders a defined empty state, not `undefined` or `?–?`.
- [ ] `cd frontend && npm run build` **and** `npm run lint` both pass — the build no longer lints, see CLAUDE.md.

## Blocked by

None — can start immediately. Should land before issue 09.

**2026-09-08 — shipped.** Was more urgent than filed: the table was not merely showing empty
columns, it was rendering **`undefined missing`** on every lossy row — an invented data-loss
alarm — because `BundleSummary` stopped serving the header fields at issue 05 and the
frontend was never moved to the new contract.

- `lib/api-services.ts` — `DiagnosticBundle` rewritten to match `BundleSummary`. It had
  declared seven fields the API no longer sends.
- `components/DiagnosticBundles.tsx` — **Seq** and **Records** replaced by a single
  **Window (IST)** column (`window_start_ist`–`window_end_ist`), `—` when unanchored, and a
  `~approx` marker when `time_approximate`, since an approximate window must never be read
  as loss evidence.
- Loss badge no longer claims a count of lost records — that number is unobtainable
  (ADR 0030). It now reads `N ring wraps` (overwriting happening *now*) or `Xm silence`
  (measured time). Wraps take precedence; with no wraps the silence is definitionally the
  cause, since `lossy` is computed server-side against the gap threshold.
- Timestamps render with an explicit `timeZone: "Asia/Kolkata"` per the repo-wide rule.

Verified: lint 0 errors / 7 baseline warnings, build succeeded, backend suite 63 passed.
Not addressed here: pagination (issue 12) — the table still shows only the newest 50.
