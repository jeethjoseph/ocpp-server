# 01 — Tariff: enforce one-tariff-per-charger (dedup + UNIQUE(charger_id) + race-safe upsert)

Status: ready-for-agent

## What to build

A charger can currently accumulate more than one charger-specific `Tariff` row. The admin charger-update path upserts a tariff with a non-atomic get-or-create (`Tariff.update_or_create(charger_id=…)`), and there is **no DB uniqueness** on `tariff.charger_id`. Two concurrent writes — observed in prod as a double-submitted `PUT /api/admin/chargers/{id}` (charger_id 38, two identical rows inserted ~2 ms apart) — both pass the "does it exist?" check and both INSERT. Every later edit of that charger then raises `tortoise.exceptions.MultipleObjectsReturned`.

One charger-specific tariff per charger **is** the real domain invariant: `get_applicable_tariffs_for_chargers` resolves *the* charger-specific tariff and falls back to the global tariff, and every read assumes a single row. Enforce that invariant at the database level and make the upsert race-safe.

- Aerich migration (generated via `aerich migrate`, **not** hand-written, per project convention) that: (1) removes duplicate charger-specific tariff rows keeping the earliest `id` — the observed duplicates are byte-identical so no tariff value changes; then (2) adds a `UNIQUE` constraint on `tariff.charger_id`. Postgres treats NULLs as distinct, so global tariffs (`charger_id IS NULL`, `is_global = true`) are unaffected and multiple may coexist.
- Harden the tariff write in the admin charger create/update paths to catch `IntegrityError` from a lost race and resolve it as an update of the existing row, rather than surfacing a 500.

## Acceptance criteria

- [ ] A charger cannot hold two `Tariff` rows — a second insert for the same `charger_id` raises `IntegrityError` at the DB level.
- [ ] Global tariffs are unaffected: multiple rows with `charger_id IS NULL` remain allowed.
- [ ] The migration de-duplicates existing rows (keep earliest `id`) **before** adding the constraint, and applies cleanly forward on a DB that already contains a duplicate (repro: prod had `charger_id = 38` with 2 rows).
- [ ] Editing a charger's tariff no longer 500s under a concurrent double-submit — the second writer resolves to an update, not `MultipleObjectsReturned`.
- [ ] Per-file pytest covers: constraint rejects a 2nd tariff per charger; global tariffs still allow multiple NULL-`charger_id` rows; the concurrent/duplicate update path does not raise.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s) (baseline flakes excepted per CLAUDE.md).

## Notes

- Dedup is folded into the migration (rather than a separate manual prod `DELETE`) so it self-heals across staging and prod on deploy, and protects staging if it ever races into a duplicate.
- Root cause and evidence: a non-atomic get-or-create with no backing unique constraint. `SELECT … FOR UPDATE` cannot lock a not-yet-existing row, so concurrent first-time writes both insert.

## Blocked by

None - can start immediately.

## Comments

**2026-07-03 — implemented.** Migration `47_20260703082906_tariff_unique_charger.py` (dedup keeping min(id), then `CREATE UNIQUE INDEX` on `tariff.charger_id`); `Tariff.Meta.unique_together = [("charger",)]` in `models.py`; race-safe `_upsert_charger_tariff` helper (catches `IntegrityError` → update) replacing the inline upsert in `update_charger`. Regression tests in `tests/test_tariff_unique_charger.py` (3 pass). Verified locally: migration deduped a seeded duplicate to one row and created the index; a 2nd charger tariff is rejected; multiple global (NULL) tariffs still allowed. Existing `test_chargers` / `test_tariff_*` suites green (45). No aerich drift.

Deploying this migration also resolves the prod incident — the dedup step removes charger 38's duplicate (`tariff id=17`) automatically, so no separate manual prod DELETE is needed.
