# Endpoint hardening: per-session error isolation + metrics

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Make `/api/public/qr-active-sessions` resilient to per-row failures and observable in production.

- Wrap each candidate session's classification + KPI computation in a `try/except`. If one session throws, log the failing `qr_payment_id` with the exception, increment a `Custom/ActiveSession/SessionComputeError` counter, and skip the row — the rest of the response is unaffected.
- Add `OCPPMetrics`-style New Relic counters at the existing project's metrics surface:
  - `Custom/ActiveSession/Request` — every successful response.
  - `Custom/ActiveSession/CacheMiss` — every time the Redis `qr_session:{txn_id}` cache is missing and the DB fallback runs.
  - `Custom/ActiveSession/SessionComputeError` — per-row computation failure.
  - Sub-state distribution counter: `Custom/ActiveSession/SubState/<waiting|charging|paused|stopping>`.
- Add a regression test for the race-window case: `QRPayment.status=CHARGING` AND `Transaction.transaction_status=STOPPED`. The classifier currently treats this as "txn no longer active" and excludes the row — this is correct behavior, but is not explicitly asserted today.

## Acceptance criteria

- [ ] A malformed row (e.g. missing `start_meter_kwh`, a Redis value type drift) on one session does not 500 the request; the other sessions still render.
- [ ] Each metric counter increments under its documented condition (verify in pytest with a `MetricsCollector` mock or equivalent to the pattern used elsewhere in the repo).
- [ ] The CHARGING + STOPPED race-window test exists and asserts the row is excluded from the response.
- [ ] Existing tests still pass; full `tests/test_public_qr_active_sessions.py` is green.

## Blocked by

None — can start immediately.
