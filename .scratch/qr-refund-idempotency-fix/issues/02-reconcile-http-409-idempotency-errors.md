# Recognize and reconcile HTTP 409 idempotency errors

Status: done

## What to build

When Razorpay returns HTTP 409 ("Different request with the same idempotency key has already been processed."), the refund code currently lets it fall through to the generic `Exception` branch in `razorpay_service.refund_payment`, so the payment is marked `REFUND_FAILED` with the raw 409 string and the 30-minute `BillingRetryService` retries it forever — it can never succeed because the colliding key is permanent.

Handle 409 as a first-class, recoverable case, mirroring the existing `RazorpayAlreadyRefundedError` path:

- Map the 409 idempotency response to a distinct exception class in `razorpay_service` instead of a generic `Exception`.
- On 409, call `find_refund_for_payment(razorpay_payment_id)` to reconcile: if a matching refund already exists at Razorpay, persist its `razorpay_refund_id` / `speed_processed` and mark the row `REFUNDED`. If no refund exists (the key was consumed by a *different* payment in a shared account — the real scenario here), record a distinct, **non-retryable** failure reason so the retry loop stops hammering it.
- This is defense-in-depth alongside slice 01; the unique-key fix prevents new collisions, this slice ensures any remaining 409 is classified correctly rather than retried indefinitely.

## Acceptance criteria

- [ ] Razorpay 409 idempotency responses map to a dedicated exception class, not generic `Exception`
- [ ] On 409 with a reconcilable existing refund: row becomes `REFUNDED` with `razorpay_refund_id` populated
- [ ] On 409 with no existing refund: row carries a distinct, non-retryable failure reason and is excluded from the `BillingRetryService` retry batch
- [ ] Unit tests cover both 409 branches (reconcilable / not reconcilable)
- [ ] `docker exec ocpp-backend pytest` green for the affected refund/billing test files (baseline flakes per CLAUDE.md excepted)

## Blocked by

- None - can start immediately (independent of slice 01)

## Comments

**2026-06-09 — implemented (local; not yet deployed).**

- `services/razorpay_service.py`: added `RazorpayIdempotencyConflictError` + `_is_idempotency_conflict_error()`. `refund_payment` now maps an HTTP 409 (or an "idempotency key" message) to the dedicated exception (raised before the generic `Exception`) and re-raises it through the outer guard.
- `services/qr_payment_service.py`: added canonical non-retryable marker `IDEMPOTENCY_CONFLICT_NO_REFUND = "idempotency_conflict_no_refund"` and a shared `QRPaymentService._reconcile_conflict()` helper (fetch existing refund → REFUNDED, else REFUND_FAILED + marker; caller saves). The already-refunded branch in `_full_refund` was refactored onto this helper (behavior preserved), and a new 409 branch added there and in the partial-refund path of `process_qr_session_billing`.
- `services/billing_retry_service.py`: the retry-eligibility filter now also excludes `IDEMPOTENCY_CONFLICT_NO_REFUND`, and the retry loop catches the conflict to reconcile (→ success) or mark the row non-retryable so the next sweep skips it.
- Tests added to `tests/test_qr_payment_service.py` (7): both 409 branches at `_full_refund` and the partial path (reconcile → REFUNDED / no-refund → marker), retry sweep excludes marker rows, a retry that 409s gets marked non-retryable, and the razorpay_service HTTP-409→exception mapping. Run: `docker exec ocpp-backend pytest tests/test_qr_payment_service.py tests/test_transaction_finalizer.py tests/test_disconnect_resume_integration.py tests/test_public_qr_active_sessions.py` → **77 passed**, no regressions.
