# Test gap fill: cache-miss fallback and rate limit on active-sessions endpoint

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Close two missing test coverage areas on `/api/public/qr-active-sessions`.

1. **Cache-miss fallback test.** Assert that when no `qr_session:{txn_id}` Redis row exists for an active transaction, the endpoint still returns the correct `spent_so_far` / `refund_if_stopped_now` by recomputing from the DB-side `Tariff`. Distinct from the happy path because the cache-write contract is established later in the flow than the read contract.
2. **Rate limit ceiling test.** Fire the 21st request inside a 60-second window from the same client IP and assert `429`. Match the testing pattern used by `tests/test_public_qr_transactions.py` if one exists; otherwise introduce the pattern. Make sure the `RedisConnectionManager.rate_limit_check` key is flushed before the test (the conftest already does this for `ratelimit:public_qr_transactions:*` — extend to `ratelimit:public_qr_active_sessions:*` or replace with a wildcard flush).

## Acceptance criteria

- [ ] Cache-miss test asserts numeric equality between cached-path and fallback-path responses for the same session.
- [ ] Rate-limit test fires N+1 requests and asserts the boundary returns 429 with the same error envelope as the history endpoint.
- [ ] `tests/test_public_qr_active_sessions.py` ends green after the additions.

## Blocked by

- `.scratch/active-session-on-my-charges/issues/04-endpoint-hardening-error-isolation-metrics.md` (changes the error-handling contract these tests interact with)
- `.scratch/active-session-on-my-charges/issues/06-api-contract-cleanup.md` (response field rename affects assertions)
