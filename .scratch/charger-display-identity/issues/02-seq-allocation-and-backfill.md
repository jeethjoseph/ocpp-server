# Sequence allocation and backfill ordering

**Superseded 2026-08-27 by ADR 0028.** There is no sequence to allocate. The code is
the `VOW####` stencil already painted on the unit and already recorded in
`Charger.name`, re-padded to five digits and given a per-environment series. So the
concurrency question resolves to a `UNIQUE` constraint plus a typed 409 (creation is
rare and admin-driven), the storage question resolves to *stored* (the code derives
from nothing mutable), and the backfill is machine-derived rather than surveyed — see
`.scratch/charger-asset-code/`. Allocation for genuinely new units is strictly
monotonic `max + 1`; codes are never reused and gaps are never backfilled.
Still genuinely open: the Aerich migration shape (add nullable + CHECK → backfill →
flip NOT NULL).

Status: ready-for-human
Labels: wayfinder:grilling
Assignee: jeethjoseph (session 2026-07-31)
Blocked-by: (none)

## Question

The code embeds a per-station sequence assigned at creation. Decide the allocation
mechanics and the backfill:

- Concurrency: two chargers created simultaneously at one station must not get the
  same seq. Options: `max(seq)+1` inside a transaction with a unique constraint on
  `(station_id, seq)` + retry; a per-station counter row; or accept a plain unique
  constraint violation surfacing to the admin (creation is rare and admin-driven).
- Storage: store the rendered code string (unique, indexed) vs store
  `(station_id, seq)` and render on read. Note immutability-on-move argues for
  storing the rendered string (the station FK can change; the code must not).
- Backfill: existing chargers get codes in creation order (`id` order) within each
  station — confirm `id` order is acceptable as "creation order" (staging shows a
  gap: charger id 8 is missing; gaps in seq are fine?).
- Migration route: per repo rules this must be Aerich-generated; backfill is a
  data migration — confirm the two-step shape (schema migration + backfill script
  or RunSQL) with the driver.

Output: allocation mechanism, storage shape, backfill ordering rule.
