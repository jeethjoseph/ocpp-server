# Drop the stale UNIQUE constraint on `charger_qr_code.charger_id`

Status: ready-for-agent

## What to build

An admin cannot recreate a charger's QR code after closing the existing one. `POST /api/admin/qr-codes` returns 500 with an asyncpg `UniqueViolationError` on the constraint `charger_qr_code_charger_id_key`. Reproduced on staging 2026-05-25 for charger `VOW0004` (4 failed attempts in the backend log).

### Root cause

The `charger_qr_code` table still carries an inline `UNIQUE(charger_id)` constraint that Postgres named `charger_qr_code_charger_id_key` (PG's default for inline UNIQUE in CREATE TABLE). Migration `12_20260315154019_allow_qr_regeneration_drop_admin.py` *intended* to drop it, but used the wrong name:

```sql
DROP INDEX IF EXISTS "uid_charger_qr__charger_bc6f6e";  -- never existed
```

Because it was `IF EXISTS`, the statement silently no-op'd and the migration ran clean. The constraint is still live on staging (verified via `pg_indexes`) and almost certainly on prod.

The `ChargerQRCode` model in `backend/models.py` has no `unique=True` on the `charger` FK, so the Python side has been correct all along — only the DB schema is stale.

### Plan

1. Run `docker exec ocpp-backend aerich migrate --name drop_charger_qr_code_charger_id_unique` first to confirm Aerich generates nothing (model and snapshot already agree). Document the refusal in the PR description.
2. Hand-write a new Aerich migration file `NN_YYYYMMDDHHMMSS_drop_charger_qr_code_charger_id_unique.py` whose `upgrade()` runs:
   ```sql
   ALTER TABLE charger_qr_code DROP CONSTRAINT IF EXISTS charger_qr_code_charger_id_key;
   ```
   and whose `downgrade()` re-adds it with the same name for reversibility.
3. Apply locally with `docker exec ocpp-backend aerich upgrade`, verify via `\d charger_qr_code` that the constraint is gone.
4. Ships through normal `make staging-deploy` → `make prod-deploy` pipeline. No emergency SSM SQL on either env — the migration handles both during deploy.

### Test

Add a regression test in `backend/tests/test_qr_codes.py` (or wherever the existing admin QR tests live):

- Create a charger fixture.
- `POST /api/admin/qr-codes` → expect 200, capture row `A`.
- `POST /api/admin/qr-codes/{A.id}/close` → expect 200, row `A` now `is_active=false`.
- `POST /api/admin/qr-codes` again for the same charger → expect 200, returns a new row `B` with `B.id != A.id`, both rows persist.
- Optionally: assert `await ChargerQRCode.filter(charger_id=charger.id).count() == 2`.

Mock `razorpay_service.create_qr_code` / `close_qr_code` so the test doesn't hit the real Razorpay sandbox.

## Acceptance criteria

- [ ] New Aerich migration file added under `backend/migrations/models/` with correct numbering
- [ ] `aerich upgrade` runs clean against a fresh DB and against an existing-staging-shaped DB
- [ ] `\d charger_qr_code` after upgrade shows no `charger_qr_code_charger_id_key` constraint
- [ ] Regression test passes: close-then-create on the same charger returns 200 + two persisted rows
- [ ] PR description notes that `aerich migrate` was tried first and refused (with stdout snippet)
- [ ] Existing QR tests still pass

## Blocked by

None — can start immediately. Ships in the **same PR** as `02-close-razorpay-qr-on-db-insert-failure.md`.
