# Allocate an Asset Code when a charger is created

Status: done

## What to build

A charger created through the admin API comes back with an Asset Code it did not ask
for. This is the first slice with visible behaviour: create a charger on a dev box, and
the response carries `VOWS0011`.

Allocation is `max + 1` **within the register** — the highest integer part currently
present in this database, plus one. Strictly monotonic: a code is **never reused** and
gaps are **never backfilled**, including gaps that were never allocated. That is
deliberately simpler than "reuse what is provably free", so nobody ever has to reason
about whether a hole is safe. Production's gaps at `VOW0004`/`VOW0005` therefore persist
permanently — those units live at the staging site — and production's next new unit is
`VOW0016`.

**System-allocated, never typed.** `asset_code` is not a field on `ChargerCreate` and not
editable through `ChargerUpdate`. Sending it must be a **`422`, not a silent ignore** — a
silent ignore teaches a caller that it works and produces a support ticket a year later
when someone notices the value never landed. This is what makes uniqueness structural
rather than a UX problem: no conflict to prompt about, no availability check to debounce,
no typo that can bind a wrong code to a unit.

Concurrent creation is resolved by the `UNIQUE` constraint from slice 01 plus a bounded
retry. Charger creation is rare and admin-driven, so a retry loop is proportionate and a
lock is not.

**This must land before slice 03.** Slice 03 flips `asset_code` to `NOT NULL`; if
creation cannot allocate one by then, charger creation breaks in production the moment
the migration runs.

## Acceptance criteria

- [ ] Creating a charger allocates and returns an Asset Code with no input from the caller.
- [ ] The allocated code uses the series for the current `ENVIRONMENT`, via `charger_code_series()` from slice 01 — not a hard-coded string.
- [ ] Passing `asset_code` to the create endpoint returns `422`. Passing it to the update endpoint returns `422`. Neither silently ignores it.
- [ ] Allocation is `max + 1` over the integer part, not `count + 1` — a test with a gap in the register proves the gap is not filled.
- [ ] Zero-padding is to a minimum width of four and widens past `9999` rather than truncating or wrapping.
- [ ] Two concurrent creates produce two distinct codes; the loser retries rather than erroring. A test covers this.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

- [01 — Asset Code column, Charger Purpose enum, and the environment series](01-asset-code-column-and-series.md)
