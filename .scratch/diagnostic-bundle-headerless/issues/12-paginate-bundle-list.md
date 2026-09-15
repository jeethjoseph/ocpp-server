# Paginate the Diagnostic Bundles list

Status: done

## ELI5

The list shows the newest 50 bundles (200 at most) and has no "older" button. A charger now
produces on the order of a thousand a day, so the screen holds well under an hour of history
and anything before that is simply unreachable from the UI.

We are paying S3 to keep a durable archive that nobody can open. The bundles are still there —
you just cannot get to them without a database query, which defeats the point of having a
screen at all.

## What to build

The admin bundle list takes a `limit` (default 50, max 200) and nothing else — no
offset, no cursor. It returns the newest N and there is no way to reach anything older.

That was fine when uploads were rare. A charger on the current cadence produces on the
order of a thousand bundles a day, so the default page is under an hour of history and
the hard ceiling is a couple of hours. Any investigation older than that is unreachable
from the UI, which defeats the point of a durable archive.

Add real pagination to the endpoint and the table.

**One invariant to preserve.** The endpoint deliberately fetches `limit + 1` rows so the
oldest bundle on the page still has a predecessor to measure its silence gap against;
without it the last row on every page would always read as having no gap before it. A
naive offset scheme reintroduces exactly that bug at every page boundary — the gap for
the first row of page 2 must still be measured against the last row of page 1.

## Acceptance criteria

- [x] Older bundles are reachable from the UI beyond the first page.
- [x] The silence-gap calculation is correct **across page boundaries** — the first row of any page shows the gap to the bundle that actually precedes it, not a blank.
- [x] A test covers the boundary case specifically: the gap on the first row of page 2 matches what it would be on an unpaginated list.
- [x] Page size stays bounded; the endpoint cannot be asked for an unbounded scan.
- [x] `cd frontend && npm run build` **and** `npm run lint` both pass.

## Blocked by

None — can start immediately.

**2026-09-08 — shipped.**

**Keyset, not offset.** The endpoint takes `before=<bundle id>` and returns
`{items, next_cursor}`. The cursor row's own `(created_at, id)` is compared against, so
new arrivals mid-browse cannot shift the page under the reader — which matters precisely
because the volume that motivated this issue (~1000/day) also guarantees rows land while
someone is paging. `id` breaks the tie, since retries land in the same second.

**On the boundary invariant.** The issue phrased it as "the first row of page 2 must be
measured against the last row of page 1". That is the right worry but the wrong direction:
a row's predecessor is the bundle *older* than it, so it is either on the same page or is
the `limit + 1` extra row — never on the previous page. Paging therefore cannot change any
row's gap, and the existing `limit + 1` fetch is exactly what guarantees it. Kept, with the
reasoning written down at the fetch.

The pairing is now `_pair_with_predecessor(bundles, limit)`, extracted so the invariant is
testable as a pure function rather than only through the endpoint. Two tests added:

- `test_paging_does_not_change_any_bundles_predecessor` — walks two pages and asserts every
  row pairs with the same predecessor it would have had unpaginated. This fails if the
  `limit + 1` fetch is ever dropped: page 1's last row pairs with `None` instead of the real
  predecessor.
- `test_the_last_row_of_the_final_page_has_no_predecessor` — records that a trailing `None`
  is correct, not a bug, so it is not "fixed" later.

Frontend: a **Load older** control that appends rather than replaces — dropping the rows
already on screen would lose the reader's place mid-investigation — and disappears when
`next_cursor` is null.

Verified: diagnostics suite **65 passed** (63 baseline + 2 new), lint 0 errors / 7 baseline
warnings, build compiled successfully.
