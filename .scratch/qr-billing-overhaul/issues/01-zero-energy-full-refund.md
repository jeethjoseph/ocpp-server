# Zero-energy session full refund

Status: ready-for-agent

## What to build

When a QR-funded **Charging Session** ends with `energy_consumed_kwh ≤ 0`, refund the customer the entire `amount_paid` instead of `amount_paid - platform_fee`. Razorpay's actual processing fee continues to be captured onto the `QRPayment` row (`platform_fee`, `razorpay_commission`, `razorpay_gst`) for ops and reconciliation, but the refund formula ignores it. VoltLync absorbs the original capture fee and any refund-processing fee as P&L loss.

No **GST Invoice** is issued for zero-energy sessions (the invoice service already short-circuits on `energy <= 0` — verify the path stays intact).

See [ADR 0002](../../../docs/adr/0002-zero-energy-full-refund.md) and [CONTEXT.md](../../../CONTEXT.md) for the policy rationale and glossary.

## Acceptance criteria

- [ ] A QR session that finalises with zero metered energy results in a Razorpay refund equal to the original `amount_paid` (verified via captured Razorpay API call in integration test).
- [ ] The `QRPayment` row for that session has `refund_amount == amount_paid` and `status = REFUNDED`.
- [ ] The `QRPayment` row still has the **Actual platform fee** populated (non-zero) from the original payment webhook.
- [ ] No `GSTInvoice` row is created for the zero-energy session.
- [ ] Existing partial-consumption refund behaviour (over-payment refund formula, energy > 0) is unchanged.
- [ ] Idempotency preserved: a repeated finalisation call does not issue a second refund (the existing `razorpay_refund_id` guard still works).
- [ ] Unit test covers the new refund-amount formula; integration test drives a simulated 0-kWh session end-to-end and asserts the above invariants.
- [ ] All existing tests in the QR/billing path pass (excluding the documented baseline flake in `tests/test_integration.py` + `tests/test_post_boot_state.py` noted in CLAUDE.md).

## Blocked by

None — can start immediately.
