# Globally-unique, stable refund idempotency key

Status: done

## What to build

QR-payment refunds land in `REFUND_FAILED` with `HTTP 409: Different request with the same idempotency key has already been processed.` because the Razorpay refund idempotency key is built from the **per-database primary key** (`qr_payment_{id}`), while staging and prod **share the same Razorpay live account** (QR requires live mode). Staging qr_payment #235 and prod qr_payment #235 both emit key `qr_payment_235`; whichever environment refunds that integer id first registers the key with its body, and the other env's later refund (different amount/notes) collides → 409. Confirmed 2026-06-09: 5 staging customers genuinely unrefunded (`count=0` at Razorpay) while prod holds the same ids as `REFUNDED` with different amounts.

Make refund idempotency correct end-to-end:

- Derive the idempotency key from the **globally-unique `razorpay_payment_id`** (which is unique across the whole Razorpay account) instead of the local PK.
- Make all three refund call sites send a **byte-identical request body** for the same payment — same `notes` keys and values — so a repeat call with the same key replays the original refund (HTTP 200) instead of returning 409. Today the original refund (`process_qr_session_billing` / `_full_refund`) and the retry (`BillingRetryService`) send different `notes`, which would 409 even within a single environment once the original reached Razorpay.

This is the root-cause prevention fix. It does not retroactively fix the already-stuck rows (see slice 04).

## Acceptance criteria

- [ ] Refund idempotency key is derived from `razorpay_payment_id`, not the local `qr_payment.id`
- [ ] The original refund path and the retry path produce an identical request body (same `notes`) for the same payment
- [ ] Unit test: two payments with different `razorpay_payment_id` produce different keys; the same payment produces the same key across the original and retry paths
- [ ] Unit test: a same-key, same-body retry is treated as an idempotent replay (no 409 raised by our code path)
- [ ] No regression in existing QR billing / refund tests
- [ ] `docker exec ocpp-backend pytest` green for the affected refund/billing test files (baseline flakes per CLAUDE.md excepted)

## Blocked by

- None - can start immediately

## Comments

**2026-06-09 — implemented (local; not yet deployed to staging/prod).**

- Added `build_refund_call_kwargs(qr_payment, refund_amount)` in `services/qr_payment_service.py` as the single source of truth for refund request params:
  - `idempotency_key = f"refund_{razorpay_payment_id}"` (globally unique; was `qr_payment_{id}`)
  - `notes = {"qr_payment_id": str(id)}` (deterministic/minimal; dropped variable transaction reason + "Retry:" prefix)
  - `speed`: `optimum` iff instant-refund flag on AND `refund_amount >= amount_paid` (full refund) — derived from the row so the retry reproduces it without extra state.
- All three call sites now route through the helper: `process_qr_session_billing`, `_full_refund`, and `BillingRetryService._process_failed_qr_refunds` (function-local import to avoid the existing circular import).
- Tests added to `tests/test_qr_payment_service.py`: key derives from payment_id not PK; same-PK/different-payment-id → distinct keys; deterministic minimal notes; speed truth table (full/partial/kill-switch); original≡retry parity; end-to-end retry-sweep clears a 409-stuck row with the new key. `docker exec ocpp-backend pytest tests/test_qr_payment_service.py` → 50 passed; adjacent suites (`test_transaction_finalizer`, `test_disconnect_resume_integration`) green.

**⚠️ Deploy interaction with issue 04:** once this is deployed to staging, the 30-min `BillingRetryService` sweep will retry the 5 stuck rows (#227/230/232/235/236) with the new non-colliding key and **auto-refund ~₹253** on the next tick — performing slice 04's remediation without the HITL gate. Decide before deploying to staging: (a) accept the auto-remediation, or (b) gate it (pause the retry sweep / temporarily exclude those rows) and run slice 04 manually under approval.
