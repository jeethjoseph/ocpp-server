# Tariff cache: Decimal preservation + cache-miss drift warning

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Resolved the HITL design call on tariff handling (review item #2): **accept the cache-miss drift** (live tariff matches final-billing tariff, so the customer's "Spent so far" stays consistent with what they will actually be charged), but emit a structured warning + counter when it happens so we can detect operator-edits-mid-session in production. No schema change.

Additionally, fix the related precision leak (#11): the `qr_session:{txn_id}` Redis cache stores `tariff_rate` and friends as **float** via `float(tariff.rate_per_kwh)`, which round-trips through float on every read. Switch to a Decimal-preserving format (store as string; readers parse back as Decimal) and document the contract.

- On cache miss in the active-sessions endpoint AND in `QRPaymentService.check_budget_and_auto_stop`, log a `WARNING` with the transaction_id and a `Custom/QrSession/CacheMissDrift` counter. The counter from issue 04's metrics work is on the read-side; this is on the write/rebuild side and is a different signal — name it accordingly to avoid double-counting.
- Update `cache_session_on_start` (`qr_payment_service.py`) to serialize Decimal fields as strings, not floats.
- Update `check_budget_and_auto_stop` and the active-sessions endpoint's `_resolve_session_context` to deserialize via `Decimal(value)` instead of `float(value)`.
- Add a one-time backward-compat fallback: if the cached field is a `float` (legacy in-flight rows), still accept it via `Decimal(str(float_value))`. Document the migration window in a comment (one TTL = 24h is enough).

## Acceptance criteria

- [ ] New QR session caches written after deploy contain string-form Decimals; existing float-form caches in flight still read correctly for one TTL window.
- [ ] Cache-miss path logs a WARNING + increments a counter — verified in pytest with a fresh transaction that has no cached session.
- [ ] No customer-facing math change — `spent_so_far` for a stable tariff is identical before and after.
- [ ] Existing `tests/test_qr_payment_service.py` and `tests/test_public_qr_active_sessions.py` still pass.

## Blocked by

None — can start immediately.
