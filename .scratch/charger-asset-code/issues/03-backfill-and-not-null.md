# Backfill every charger from the explicit map, then flip to NOT NULL

Status: done

## What to build

Give every existing charger an Asset Code and a Purpose, then make the code mandatory.

**Apply an explicit map, not a derivation.** `upgrade()` must never read `Charger.name`.
The map is generated offline from `../asset-code-assignments.csv` and baked into the
migration as literal data, so what a reviewer reads is exactly what executes. A
derivation would re-read `name` at run time — and `name` is freely editable by any admin,
so anyone touching it between review and deploy would silently change the result. This is
the last time anything in this codebase trusts `name`.

**Key the map on `charge_point_string_id`, never `Charger.id`.** Row ids differ per
register (production 25–38, staging 1–10) and can be reused if a row is deleted and
recreated. The UUID is immutable and unique.

```python
ASSET_CODE_BACKFILL = {
    "production": {"7536bc02-…": ("VOW0001", "PUBLIC"), …},   # 13 rows
    "staging":    {"ffeadb01-…": ("VOWS0001", "PUBLIC"), …},  #  9 rows
}
```

Select by `ENVIRONMENT` inside `upgrade()`, the same way migration 50 builds its
per-register `CHECK` from one shared file. **Development is deliberately not mapped** — a
local DB holds arbitrary chargers, so dev allocates sequentially instead of requiring a
map. Otherwise every dev box breaks on migrate.

The same map sets `purpose = TEST` on the ten bench units. That classification is the
only inferred column in the worksheet, and it is inferred from the name looking like a
test unit — which is why the CSV was reviewed by a human before it got here. A fleet unit
wrongly marked `TEST` stops billing and vanishes from public surfaces once slices 06 and
07 ship.

Four guards, each **raising rather than skipping quietly**:

1. Every UUID in the map exists in the target register.
2. Every row with `asset_code IS NULL` is covered by the map — this is what catches a
   charger created between CSV generation and deploy.
3. Only rows with `asset_code IS NULL` are written, so a re-run is idempotent.
4. Post-condition: zero `NULL` codes before the `NOT NULL` flip.

Because the map is literal and reviewable, this slice is fully deterministic — which is
exactly what lets slice 00 gate slice 04 rather than gating this one. A wrong value here
is an `UPDATE`; a wrong value after 04 is on an issued invoice.

## Acceptance criteria

- [ ] `upgrade()` contains no reference to `Charger.name` — the map is literal data.
- [ ] The map is keyed on `charge_point_string_id`.
- [ ] Production and staging maps are selected by `ENVIRONMENT`; development allocates sequentially and does not require a map entry.
- [ ] Each of the four guards raises on violation. Tests cover at least guard 1 (unknown UUID) and guard 2 (uncovered row).
- [ ] Re-running the migration is a no-op, not a duplicate-key error.
- [ ] The ten bench units end with `purpose = TEST`; every fleet unit ends `PUBLIC`.
- [ ] `asset_code` is `NOT NULL` afterwards, and the flip is in the same migration as the backfill so no window exists where the constraint is on and rows are empty.
- [ ] Production's gaps at `VOW0004` and `VOW0005` are **not** filled.
- [ ] Aerich-generated. Never hand-edit an applied migration.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

- [02 — Allocate an Asset Code when a charger is created](02-allocation-on-create.md)
