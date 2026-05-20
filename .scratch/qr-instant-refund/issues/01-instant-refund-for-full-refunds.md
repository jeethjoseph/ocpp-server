Status: ready-for-agent

# Enable Razorpay instant refunds for all QR full-refund flows

## What to build

Switch every QR full-refund path to request Razorpay's instant-refund mode (`speed=optimum`) so customers see the money back in minutes instead of 5–7 working days. The change applies to all six call sites of `QRPaymentService._full_refund`:

1. Zero-energy at StopTransaction (`handle_charging_failure`)
2. Stale payment after webhook delay (`process_payment_captured`)
3. Concurrent payment rejected on busy charger (`process_payment_captured`)
4. Charger not connected at start time (`_start_charging`)
5. RemoteStart failed after retries (`_start_charging`)
6. Plug-in timeout (`_wait_for_plug_in_then_start`)

The partial-refund path inside `process_qr_session_billing` (unused-credit refund when a session billed less than `amount_paid`) stays on Razorpay's default `normal` speed — it is "here's your change," not "we failed you."

VoltLync absorbs Razorpay's per-refund instant fee (~₹5–₹6 + 18% GST per UPI refund), same philosophy as the original gateway-fee absorption in ADR 0002. No new ledger entity is introduced — the existing `QRPayment.refund_amount` / `razorpay_refund_id` / `status` columns remain the source of truth.

A kill-switch env var `RAZORPAY_INSTANT_REFUND_ENABLED` (default `true`) lets ops disable instant mode in an incident without a code change. When the flag is off, refunds revert to Razorpay's default speed silently.

Razorpay's `optimum` mode is best-effort — it falls back to `normal` server-side if the payment method or rails don't support instant. The refund response includes `speed_processed` so we log what actually happened (no client-side fallback needed). Idempotency via the existing `X-Refund-Idempotency` header is unchanged.

## Acceptance criteria

- [ ] `RazorpayService.refund_payment` accepts an optional `speed: Optional[str] = None` kwarg and forwards it as `refund_data["speed"]` when set.
- [ ] `refund_payment` logs both `speed_requested` (input) and `speed_processed` (from response) on every refund.
- [ ] `QRPaymentService._full_refund` passes `speed="optimum"` when `RAZORPAY_INSTANT_REFUND_ENABLED` env var is truthy; omits it (or passes None) when off.
- [ ] `QRPaymentService.process_qr_session_billing` (partial-refund branch) does NOT pass `speed` — partial refunds remain on normal speed.
- [ ] `RAZORPAY_INSTANT_REFUND_ENABLED` is present (default `true`) in: `backend/.env.example`, `.env.staging.example`, `.env.prod.example`, `docker-compose.yml`, `docker-compose.staging.yml`, `docker-compose.prod.yml`.
- [ ] `backend/main.py` startup logs whether instant refund is enabled or disabled.
- [ ] `docker exec ocpp-backend env | grep RAZORPAY_INSTANT_REFUND_ENABLED` returns the value after a backend rebuild.
- [ ] New tests in `backend/tests/test_qr_payment_service.py` assert: full-refund path sends `speed=optimum` when flag on; full-refund path omits `speed` (or sends None) when flag off; partial-refund path never sends `speed`.
- [ ] All existing tests in `test_qr_payment_service.py` and `test_razorpay_audit_log.py` still pass.
- [ ] ADR 0002 is amended in place to note the instant-refund fee is also absorbed; reference the kill-switch env var.
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` reflect the new env var and policy clarification.

## Blocked by

None - can start immediately.
