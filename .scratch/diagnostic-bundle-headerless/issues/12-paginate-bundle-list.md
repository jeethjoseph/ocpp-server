# Paginate the Diagnostic Bundles list

Status: ready-for-agent

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

- [ ] Older bundles are reachable from the UI beyond the first page.
- [ ] The silence-gap calculation is correct **across page boundaries** — the first row of any page shows the gap to the bundle that actually precedes it, not a blank.
- [ ] A test covers the boundary case specifically: the gap on the first row of page 2 matches what it would be on an unpaginated list.
- [ ] Page size stays bounded; the endpoint cannot be asked for an unbounded scan.
- [ ] `cd frontend && npm run build` **and** `npm run lint` both pass.

## Blocked by

None — can start immediately.
