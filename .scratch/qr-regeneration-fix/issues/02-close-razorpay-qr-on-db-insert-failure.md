# Close the Razorpay QR on DB-insert failure in `_create_qr_for_charger`

Status: ready-for-agent

## What to build

`_create_qr_for_charger` in `backend/routers/qr_codes.py` creates a QR on Razorpay's side first, then inserts the local `ChargerQRCode` row. If the DB insert fails (today's symptom: the stale UNIQUE constraint; tomorrow's: anything else — Postgres connection blip, future check constraint, race condition), the Razorpay QR is already live and orphaned. It pollutes the merchant view forever.

Today's staging produced 4 such orphans from the constraint-violation incident:
`qr_StVw78FvfWrofx`, `qr_StVw9hlw7WgWZJ`, `qr_StVwIbN2nJ6a3Y`, `qr_StVwKqSAIQCNvK`.

Slice 1 fixes today's specific cause. This slice fixes the category — any future failure in the post-Razorpay-call path will self-clean.

### Plan

In `_create_qr_for_charger`:

1. Keep the existing Razorpay call (`razorpay_service.create_qr_code(...)`) as-is.
2. Wrap the `await ChargerQRCode.create(...)` call (and only that) in a try/except.
3. On any exception, call `razorpay_service.close_qr_code(result["id"], account_id=None)` inside a nested try/except — log a warning if the close fails, do not let it mask the original exception.
4. Re-raise the original exception so the existing 500 error path in `create_qr_code`/`regenerate_qr_code` still fires and the admin sees a real error.

Keep the helper under 40 lines (CLAUDE.md). If the try/except pushes it over, extract the compensating-close into a sibling helper `_close_orphan_razorpay_qr(qr_id: str) -> None`.

This affects both the `POST /api/admin/qr-codes` and `POST /api/admin/qr-codes/{id}/regenerate` paths since both go through `_create_qr_for_charger`.

### Test

Add to `backend/tests/test_qr_codes.py`:

- Mock `razorpay_service.create_qr_code` to return `{"id": "qr_TEST_FAKE", "image_url": "...", "short_url": "..."}`.
- Mock `ChargerQRCode.create` (or set up a real constraint that will violate) to raise `tortoise.exceptions.IntegrityError("simulated")`.
- Mock `razorpay_service.close_qr_code`.
- Call `POST /api/admin/qr-codes` for a charger.
- Assert response is 500.
- Assert `razorpay_service.close_qr_code` was called exactly once with `"qr_TEST_FAKE"`.
- Assert no `ChargerQRCode` row exists for the charger.

Second test for the regenerate path: identical setup, hit `POST /api/admin/qr-codes/{existing_id}/regenerate`. Asserts the orphan-close fires for the *new* attempted QR (not the old one being replaced).

## Acceptance criteria

- [ ] `_create_qr_for_charger` closes the Razorpay-side QR on any DB-insert failure
- [ ] Original exception still propagates (caller still returns 500)
- [ ] Failure to close on Razorpay is logged but does not mask the original exception
- [ ] Helper(s) stay under 40 lines each
- [ ] Two new tests pass: one for `create_qr_code`, one for `regenerate_qr_code`
- [ ] Existing QR tests still pass

## Blocked by

None — can start immediately. Ships in the **same PR** as `01-drop-stale-charger-id-unique-constraint.md`.

## Out of scope

Cleanup of the 4 existing staging-side orphan QRs (`qr_StVw78FvfWrofx`, `qr_StVw9hlw7WgWZJ`, `qr_StVwIbN2nJ6a3Y`, `qr_StVwKqSAIQCNvK`). Operator can close them via the Razorpay dashboard if desired; they're harmless (no webhook handler matches them, so no payments can accrue) and skipped per maintainer decision.
