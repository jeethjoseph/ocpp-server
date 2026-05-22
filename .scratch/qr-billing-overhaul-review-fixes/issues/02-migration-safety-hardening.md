# Migration 36 safety hardening + smoke-test rework

Status: ready-for-agent

## What to build

Three related concerns flagged in the senior review of the qr-billing-overhaul work, all touching the all-in tariff migration and its smoke test:

1. **H3 — migration hardcodes `0.98`.** The SQL inside migration 36 freezes "we deduct 2% gateway fee" at the moment the migration was written. That's intentional and correct (migrations should be deterministic and auditable). The risk is **silent drift**: if `RAZORPAY_PLATFORM_FEE_PERCENT` is changed in the env between migration-write time and migration-run time on a particular environment, the runtime back-derivation (`× (1 − fee/100)`) disagrees with the migration's backfill (`× 0.98`), violating the per-row identity for every legacy-backfilled tariff.
2. **M1 — smoke test inlines the migration SQL.** `tests/test_tariff_all_in_migration.py` copies the UPDATE statement into a `MIGRATION_36_BACKFILL_SQL` constant. If someone edits the migration without updating the test (or vice versa), both still pass and the discrepancy is silent.
3. **M2 — tautology test.** `test_backfill_all_in_is_not_null_after_migration` queries `WHERE tariff_per_kwh_all_in IS NULL` against a schema that already enforces NOT NULL via the model. It always returns 0 regardless of what the migration does.

### Plan

For H3: at startup, sample a few `Tariff` rows and compute `expected_rate = all_in × (1 − RAZORPAY_PLATFORM_FEE_PERCENT/100) / (1 + gst_percent/100)`. If `abs(expected_rate − stored_rate_per_kwh) > 0.0002` on any sampled row, log a structured warning naming the affected charger(s). This catches the env-var-changed-after-migration scenario without forcing operators to make migration env-aware. Pair with a `Custom/Tariff/IdentityDrift` metric counter so ops can dashboard it.

For M1: extract the UPDATE statement in the migration file into a module-level constant (e.g., `BACKFILL_UPDATE_SQL`). Have `upgrade()` reference it. Import the same constant in the smoke test. Single source of truth.

For M2: delete the test. The "NOT NULL after migration" property is enforced structurally by the Tortoise model and validated implicitly every time anything inserts into `Tariff` without supplying `tariff_per_kwh_all_in`. A test that always passes provides false confidence.

## Acceptance criteria

- [ ] Migration 36's UPDATE statement lives in a single module-level constant inside the migration file; both `upgrade()` and the smoke test reference it.
- [ ] Startup-time identity check samples at least 10 `Tariff` rows (or all of them if fewer); warns via `logger.warning` with the charger id and the magnitude of drift for each violating row.
- [ ] `Custom/Tariff/IdentityDrift` counter increments once per startup that detects any drift (not once per drifting row — avoid alert storms).
- [ ] Manual test: change `RAZORPAY_PLATFORM_FEE_PERCENT` to `2.5` in `.env`, restart backend, confirm the warning fires for the seeded `2%` legacy tariffs.
- [ ] `test_backfill_all_in_is_not_null_after_migration` is deleted.
- [ ] Existing parameterized backfill smoke test still passes (now reading the SQL from the migration module, not a local copy).
- [ ] Full backend suite green.

## Blocked by

None — can start immediately. Slice 1 (config relocation) is independent; this can land in any order relative to it.
