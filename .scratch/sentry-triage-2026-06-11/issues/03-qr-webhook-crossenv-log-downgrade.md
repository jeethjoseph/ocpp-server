# Downgrade cross-env QR webhook "no active ChargerQRCode" from error to info

Status: ready-for-agent

Sentry: OCPP-BACKEND-R — `No active ChargerQRCode found for qr_code_id=…` (208 occurrences, production)

## What to build

When a Razorpay QR-payment webhook arrives for a `qr_code_id` that has no active `ChargerQRCode` in this database, the handler already returns gracefully (`{"status": "error", "reason": "QR code not found or inactive"}`) without raising. But it logs the miss at `error` level, generating 208 false-alarm Sentry events.

Staging and prod share the same Razorpay **live** account, so each environment receives webhooks for the other's QR codes — a "not found" here is the expected, documented cross-environment case (CLAUDE.md: "Razorpay webhook handlers gracefully skip 'not found' transactions (cross-environment events) — do not change this to raise errors").

Downgrade this specific log line so it no longer surfaces as a Sentry error. The graceful return must stay exactly as-is.

## Acceptance criteria

- [ ] The "no active ChargerQRCode" path logs at info/warning, not error, and does not create a Sentry error event.
- [ ] The handler's return value and control flow are unchanged (still skips gracefully, never raises).
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s).

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** `qr_payment_service.py:335` cross-env miss downgraded `error`→`info`; graceful return unchanged. `test_qr_cross_env_qr_code_not_found` extended with a `caplog` assertion that the miss does not log at ERROR. Passes.
