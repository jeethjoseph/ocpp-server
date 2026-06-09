# Fix retry exclusion for below-minimum refund failures

Status: done

## What to build

`BillingRetryService` excludes failed refunds from its retry batch only when `failure_reason` exactly equals the canonical marker `below_razorpay_minimum`. Sub-₹1 refunds are below Razorpay's hard ₹1.00 floor and are permanently un-refundable, so they should never be retried. But legacy rows carry the long-form message (e.g. staging row #46: `Refund for pay_... below Razorpay minimum (₹1.00): The amount must be atleast INR 1.00`) which does not match the exact-string exclusion, so they keep getting retried every 30 minutes as pure noise.

Normalize below-minimum detection so every sub-₹1 failure — canonical marker or legacy long-form — is treated as terminal and excluded from retries. Optionally backfill existing legacy rows to the canonical `below_razorpay_minimum` marker so the data is consistent going forward.

## Acceptance criteria

- [ ] Below-minimum failures are detected by a robust predicate (not an exact-string match on one marker), covering both the canonical marker and the legacy long-form message
- [ ] Such rows are excluded from the `BillingRetryService` retry batch
- [ ] Unit test: a row with the legacy long-form below-minimum message is excluded from the retry batch
- [ ] (Optional) one-off backfill normalizing existing legacy below-minimum rows to the canonical marker
- [ ] `docker exec ocpp-backend pytest` green for the affected billing-retry test files (baseline flakes per CLAUDE.md excepted)

## Blocked by

- None - can start immediately

## Comments

**2026-06-09 — implemented (local; not yet deployed).**

- `services/qr_payment_service.py`: added `BELOW_MINIMUM_REASON = "below_razorpay_minimum"` and a substring-robust predicate `is_retryable_refund_failure(failure_reason)` — returns False for the canonical below-minimum marker, the legacy long-form text (`icontains "below razorpay minimum"`, case-insensitive), and `IDEMPOTENCY_CONFLICT_NO_REFUND`; True otherwise (incl. empty/None and transient errors). Partial-refund path now uses the constant; `_full_refund` gained a `RazorpayRefundBelowMinimumError` branch that tags the canonical marker too (consistency — prevents new long-form rows).
- `services/billing_retry_service.py`: replaced the exact-match `.exclude(failure_reason__in=[...])` with a fetch + Python `is_retryable_refund_failure(...)` filter (single source of truth, robust to legacy/variant wording). Skipped rows aren't re-saved, so their `updated_at` ages them out of the `max_retry_age_hours` window — the extra fetch is self-limiting.
- Tests added to `tests/test_qr_payment_service.py`: parametrized predicate table (8 cases), legacy-long-form row excluded from the sweep (the #46 regression), transient failure still retried, and `_full_refund` below-minimum tags the canonical marker. `docker exec ocpp-backend pytest tests/test_qr_payment_service.py` → **68 passed**.

**Backfill (optional criterion) intentionally skipped.** The predicate classifies legacy long-form rows (e.g. staging #46) as non-retryable *without* any data change, so a backfill adds risk for no correctness benefit. If desired purely for data hygiene, it can be a one-off `UPDATE qr_payment SET failure_reason='below_razorpay_minimum' WHERE failure_reason ILIKE '%below Razorpay minimum%'` — but it is not required and was not run.
