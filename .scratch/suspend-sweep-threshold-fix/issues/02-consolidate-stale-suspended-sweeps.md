# Consolidate the two duplicate stale-suspended sweeps

Status: done

## What to build

The "find SUSPENDED transactions past their window and finalize them" logic
exists in two places with independently-maintained cutoffs:

- `disconnect_handler.sweep_stale_suspended_transactions` — runs once at
  startup, uses `max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + 60`.
- `billing_retry_service._cleanup_stale_suspended_transactions` — runs every
  loop cycle; after issue 01 it uses the same cutoff.

Having two copies is exactly what let the cutoffs drift apart and cause the
incident in issue 01. Extract a single shared helper (cutoff computation + the
finalize loop) so both call sites use one source of truth and the threshold can
never diverge again. Behavior-preserving refactor — no functional change beyond
both paths provably sharing the same logic.

## Acceptance criteria

- [ ] A single shared function computes the stale-suspended cutoff and
      finalizes eligible transactions.
- [ ] Both the startup sweep and the billing-retry sweep call it.
- [ ] No behavioral change vs the post-issue-01 state (same cutoff, same
      finalize reason semantics, same CAS guard).
- [ ] Existing stale-suspended tests still pass; the shared helper is unit-tested
      directly.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

- `.scratch/suspend-sweep-threshold-fix/issues/01-align-billing-retry-stale-suspended-cutoff.md`

## Comments

**Implemented 2026-06-18.** Extracted `disconnect_handler.finalize_stale_suspended_transactions(stop_reason)`
(plus `stale_suspended_cutoff_seconds()`) as the single source of truth. Both
`sweep_stale_suspended_transactions` (startup, `STALE_SUSPEND_SWEEP`) and
`BillingRetryService._cleanup_stale_suspended_transactions` (recurring,
`SUSPENDED_TIMEOUT`) now delegate to it. The billing-retry hand-rolled CAS +
billing block was removed — finalize_stopped_transaction's terminal-state guard
provides the same double-process protection and additionally runs audit log,
settlement, invoice, and zero-energy/flap cleanup that the hand-rolled path
omitted. Dropped now-unused `MeterValue` import from billing_retry_service.
Verified: 29 tests across test_billing_retry_stale_suspended, test_disconnect_handler,
test_transaction_finalizer, test_disconnect_resume_integration, test_resume_staleness_guard — all green.
