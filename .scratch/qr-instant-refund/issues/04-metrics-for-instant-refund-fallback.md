Status: ready-for-agent

# Emit metric counters for instant-refund succeeded vs fallback

## Parent

`.scratch/qr-instant-refund/issues/01-instant-refund-for-full-refunds.md`

## What to build

Issue 01 logs Razorpay's `speed_processed` outcome on every refund, but ops cannot alert on or quantify the instant-vs-fallback ratio without log aggregation. Razorpay's `speed=optimum` is best-effort — it falls back to normal speed server-side when rails are down or the payment method doesn't support instant — and a sudden spike in fallbacks is a real operational signal (rail outage, account-level rate limit, payment-method shift).

This slice adds two counters in the existing `MetricsCollector` pattern so the fallback rate is queryable from New Relic directly.

### Counters

- `Custom/QR/RefundInstantSucceeded` — incremented when a refund completed with `speed_processed == "instant"`.
- `Custom/QR/RefundInstantFallback` — incremented when `speed=optimum` was requested but `speed_processed` came back as anything other than `"instant"` (typically `"normal"`).

### Emission point

Inside `QRPaymentService._full_refund`, after the refund succeeds (both happy path and the `RazorpayAlreadyRefundedError` reconciliation path when the existing-refund dict carries a `speed_processed` field). Gate the emission on `speed_requested == "optimum"` so we don't pollute the counters when the kill-switch is off and normal-speed is intentional.

### Helper

Add a helper to `services/monitoring_service.py` mirroring the existing `record_zero_energy_stopped` shape — e.g. `OCPPMetrics.record_refund_speed(charger_id, qr_payment_id, speed_processed)`. Keep all `Custom/QR/...` naming in one place so the metric vocabulary stays discoverable.

### Tests

- Mock Razorpay to return `speed_processed: "instant"` → assert `RefundInstantSucceeded` increments, `RefundInstantFallback` does not.
- Mock Razorpay to return `speed_processed: "normal"` while `speed=optimum` was requested → assert `RefundInstantFallback` increments, `RefundInstantSucceeded` does not.
- With `RAZORPAY_INSTANT_REFUND_ENABLED=false` → assert neither counter increments (this is just a normal-speed refund, not a fallback).
- Partial refunds (`process_qr_session_billing`) never touch these counters — verify in the existing partial-refund test.

## Acceptance criteria

- [ ] `Custom/QR/RefundInstantSucceeded` counter defined and incremented on instant-processed refunds.
- [ ] `Custom/QR/RefundInstantFallback` counter defined and incremented when `optimum` was requested but the response came back as non-instant.
- [ ] Neither counter fires when `RAZORPAY_INSTANT_REFUND_ENABLED=false` (normal-speed refunds are not "fallbacks" — they were never requested as instant).
- [ ] Neither counter fires for partial refunds in `process_qr_session_billing`.
- [ ] Both the happy path and the `RazorpayAlreadyRefundedError` reconciliation path emit the right counter when the data is available.
- [ ] Helper lives in `services/monitoring_service.py` following the existing `record_*` pattern.
- [ ] Tests assert each path; `docker exec ocpp-backend pytest backend/tests/test_qr_payment_service.py` passes.

## Blocked by

None - can start immediately.

## Comments

### Files changed
- `backend/services/monitoring_service.py` — added `OCPPMetrics.record_refund_speed(charger_id, qr_payment_id, speed_processed)` helper. Increments `Custom/QR/RefundInstantSucceeded` when `speed_processed == "instant"`, else `Custom/QR/RefundInstantFallback`. Also records a `QRRefundSpeed` New Relic event for ad-hoc querying.
- `backend/services/qr_payment_service.py`:
  - Added `OCPPMetrics` to the existing `monitoring_service` import.
  - `_full_refund` happy path now calls `OCPPMetrics.record_refund_speed(...)` after the refund persists, gated on `refund_speed == "optimum"`.
  - `_full_refund` reconciliation path (`RazorpayAlreadyRefundedError` → `find_refund_for_payment`) emits the same metric, additionally gated on `existing_speed` being truthy (the existing-refund dict may not always carry `speed_processed`).

### Tests added/modified
- `test_full_refund_emits_instant_succeeded_metric` — instant outcome → metric emitted with `speed_processed="instant"`.
- `test_full_refund_emits_fallback_metric_when_response_is_normal` — fallback outcome → metric emitted with `"normal"`.
- `test_full_refund_emits_no_metric_when_flag_disabled` — kill-switch off → no metric (normal-speed refund is not a fallback).
- `test_full_refund_reconciliation_emits_metric_when_speed_present` — reconciliation path emits the metric when the existing-refund dict carries `speed_processed`.
- `test_partial_refund_does_not_emit_speed_metric` — partial refunds in `process_qr_session_billing` never touch the counters.

Tests patch `OCPPMetrics.record_refund_speed` directly (not `MetricsCollector.increment_counter`) so call counts assert at the *intent* layer — refactors inside `record_refund_speed` (e.g. swapping the counter name, adding a third bucket) don't break these tests.

### Judgment calls
- The reconciliation-path metric emission is gated on `existing_speed` being truthy in addition to `refund_speed == "optimum"`. Razorpay's `find_refund_for_payment` response shape may or may not include `speed_processed` depending on SDK/API version; emitting an `"unknown"` fallback there would over-count the fallback counter for a known data-availability gap, not a real Razorpay rail failure.
- `_full_refund` is now ~98 lines (it was already ~70 before this round). CLAUDE.md prefers <40-line functions, but splitting the row-locked transactional flow would be a higher-risk refactor than this slice should carry. Flagging for a future cleanup PR.

### Build verification
- `docker exec ocpp-backend pytest tests/test_qr_payment_service.py` → 40 passed.
