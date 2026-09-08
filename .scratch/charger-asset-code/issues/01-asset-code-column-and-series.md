# Asset Code column, Charger Purpose enum, and the environment series

Status: ready-for-agent

## What to build

The schema and policy foundation for ADR 0028, with **no behaviour change**. Nothing
reads either field yet; this slice only makes them exist and makes them impossible to
fill wrongly.

Two columns on `Charger`, deliberately independent of one another:

- **`asset_code`** — the customer-facing identity. `VARCHAR(12)`, **nullable for now**,
  `UNIQUE`, with a format `CHECK` on `^VOWS?[0-9]{4,}$` plus a series `CHECK` built in
  `upgrade()` from `ENVIRONMENT`. Slice 03 flips it to `NOT NULL` once every row has one.
- **`purpose`** — serviceability. A `CharEnumField` (`PUBLIC` | `TEST`), default
  `PUBLIC`, `NOT NULL`.

The default on `purpose` is load-bearing and not a convenience: it makes the **failure
direction fail-open**. A row missed by any later backfill keeps billing and stays
visible, so the worst case is the status quo. The previous (rejected) bay design had the
opposite property — its column was `NULL` for every row the moment it landed, so shipping
the gate first blocked every customer and shipping the filter first emptied the station
map.

`PRIVATE` is a third value in ADR 0028 with no instance in the fleet today. Tortoise
renders a `CharEnumField` as a plain `VARCHAR` with no DB enum type or `CHECK` (see
migration 42 for `availability`), so adding it later needs no migration. **Do not add it
speculatively.**

`CHARGER_CODE_SERIES` and `charger_code_series()` go in `backend/policy.py` beside
`FRANCHISEE_CODE_BLOCKS`, following migration 50's pattern for building a per-register
`CHECK` from one shared source. They belong in policy rather than env wiring for the
reason stated at the top of that file: this is a reviewed business decision, not an
invisible `.env` edit. Match the existing fail-safe direction exactly — an unknown or
empty `ENVIRONMENT` resolves to **`VOWS`, never `VOW`**, so a misconfigured box cannot
mint a production-looking code. Staging serves real paying customers, which is why the
series exists at all.

**Name the field `asset_code`.** `charger_code` is already taken in shipped code —
`backend/services/diagnostic_fanout.py` uses it as an OTLP attribute carrying the OCPP
UUID, asserted in `backend/tests/test_diagnostic_fanout.py`. Reusing the name would make
one identifier mean two different things in New Relic.

While in `backend/policy.py`: the comment above `FRANCHISEE_CODE_BLOCKS` refers to the
Asset Code's series as "VOW / VLS". The staging series is **`VOWS`**. Fix the comment.

## Acceptance criteria

- [ ] Aerich-generated migration adds both columns. Generated with `aerich migrate`, never hand-written — if Aerich refuses, stop and treat it as the stale-local-DB signal it usually is rather than hand-rolling the file.
- [ ] The series `CHECK` is built inside `upgrade()` from `ENVIRONMENT`, following migration 50's pattern, so production and staging each reject the other's series at the database level.
- [ ] `charger_code_series()` resolves an unknown, empty or `None` environment to `VOWS`. A test asserts this specifically — it is the fail-safe and a silent regression to `VOW` is the expensive direction.
- [ ] The format `CHECK` accepts `VOW0001`, `VOWS0001` and `VOW10000`, and rejects `VOW1`, `VOW001`, `vow0001` and `VLS0001`.
- [ ] `purpose` defaults to `PUBLIC` for every existing row and every newly inserted one.
- [ ] `PRIVATE` is **not** added to the enum.
- [ ] The `VOW / VLS` comment in `backend/policy.py` reads `VOW / VOWS`.
- [ ] No existing behaviour changes: no surface reads either column yet.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

None — can start immediately.
