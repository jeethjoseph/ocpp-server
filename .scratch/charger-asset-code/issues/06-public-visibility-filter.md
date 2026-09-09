# Bench units stop appearing on public surfaces

Status: done

## What to build

Five production bench units are currently listed on `/stations` and counted toward
`total_chargers`. A customer can see them, and the station's advertised capacity is
wrong. Filter `purpose != TEST` in `_fetch_stations_with_availability`, which is the one
path behind `/stations`, station detail and the no-auth map.

**Serviceability is a separate axis from liveness.** `_filter_real_chargers` in the same
module is a *liveness* predicate — connected, recent heartbeat. Do not fold this into it.
A bench unit that is online and heartbeating is perfectly live and still must not be
advertised; a fleet unit that is offline is not live and must still be counted. Two
questions, two filters.

Safe to ship any time after slice 03. Before 03 it is a no-op, because every row defaults
`PUBLIC`.

## Acceptance criteria

- [ ] `purpose = TEST` chargers do not appear on `/stations`, station detail, or the no-auth map.
- [ ] They do not count toward `total_chargers` or any other advertised capacity number.
- [ ] The five production bench units drop off; the eight fleet units remain.
- [ ] `_filter_real_chargers` is unchanged — the new filter is separate, and a test makes the distinction concrete (an online `TEST` unit is hidden; an offline `PUBLIC` unit is still counted).
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.
- [ ] `cd frontend && npm run build` **and** `npm run lint` both pass if any frontend file changes.

## Blocked by

- [03 — Backfill every charger from the explicit map, then flip to NOT NULL](03-backfill-and-not-null.md)
