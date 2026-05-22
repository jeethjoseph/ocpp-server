# `Tariff.tariff_per_kwh_all_in` schema migration and backfill

Status: ready-for-agent

## What to build

Add two new columns to the `Tariff` model and backfill them so the customer-facing displayed per-kWh number is preserved on cutover, while the new **All-in tariff** semantics take effect for all subsequent reads.

New column:

- `tariff_per_kwh_all_in: Decimal(10, 4)` — the operator-typed all-in number (per-kWh price including GST and the synthetic gateway fee). Added nullable, backfilled, then tightened to NOT NULL inside the same migration.

(The originally-planned `operator_set_all_in_at` tracking column was dropped — at two live chargers, ops handles re-entry manually. See ADR 0003.)

Backfill logic, run inside the Aerich migration's `upgrade()` as manual SQL:

```sql
UPDATE tariff
SET tariff_per_kwh_all_in = ROUND(rate_per_kwh * (1 + gst_percent / 100), 4),
    rate_per_kwh = ROUND(rate_per_kwh * 0.98, 4);
```

Then tighten the all-in column to NOT NULL.

This shrinks every existing row's `rate_per_kwh` by 2% so the back-derivation identity `tariff_per_kwh_all_in × 0.98 / 1.18 = rate_per_kwh` holds. Franchisees absorb 2% margin on legacy tariffs until they explicitly re-save (issue 05 shows them which chargers are affected).

Generate the schema-add portion with `aerich migrate` per CLAUDE.md ("Always use Aerich for migrations"). Hand-edit only the generated file to add the `UPDATE` step and the NOT NULL tighten — do not hand-write a fresh migration.

Cutover (HITL — operationally executed by humans):

1. Announce maintenance window; stop all live charging sessions (no in-flight QR sessions with cached Redis budgets).
2. `docker exec ocpp-backend aerich upgrade` against staging first, then prod.
3. Smoke check: row count unchanged; every row has both columns; back-calc identity holds within ±0.0001.

See [ADR 0003](../../../docs/adr/0003-all-inclusive-tariff-with-operator-absorption.md).

## Acceptance criteria

- [ ] Aerich generates the column-add migration; the file is hand-edited to add the backfill UPDATE and NOT NULL tighten (no hand-written migration from scratch).
- [ ] After the migration runs against a staging snapshot, every `Tariff` row has a non-NULL `tariff_per_kwh_all_in` and the back-calc identity `abs(all_in × 0.98 / 1.18 - rate_per_kwh) < 0.0001` holds.
- [ ] Migration smoke test: a pytest that loads a fixture of representative pre-migration tariff rows, applies the migration, and asserts the invariants above.
- [ ] Rollback (`aerich downgrade`) is exercised in the test to confirm it removes both columns cleanly.
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated per CLAUDE.md.

## Blocked by

None — can start immediately. Issues 04 and 05 depend on this landing.
