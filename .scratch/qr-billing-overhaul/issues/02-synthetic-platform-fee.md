# Synthetic 2% platform fee for QR billing math

Status: ready-for-agent

## What to build

Decouple the **Synthetic platform fee** (fixed 2% policy, used for all customer-facing math) from the **Actual platform fee** (real Razorpay deduction, captured for ops only). Today the single `_resolve_platform_fee` helper conflates both; this issue splits them and migrates every customer-facing math site to the synthetic helper.

Two helpers:

- `_synthetic_platform_fee(amount_paid)` — pure function returning `amount_paid × RAZORPAY_PLATFORM_FEE_PERCENT / 100`. Treats the result as all-in: commission = `amount_paid × 2/118`, GST on commission = `amount_paid × 2 × 18/118`. No DB writes.
- `_ensure_actual_fee_captured(qr_payment)` — side-effect writer that ensures the real Razorpay fee is recorded on the `QRPayment` row (`platform_fee`, `razorpay_commission`, `razorpay_gst`, `fee_source`). Sources, in priority: webhook payload (already captured at payment time), Razorpay API fetch as fallback. No return value.

Switch every customer-facing math site to the synthetic helper:

- QR session budget cap on transaction link (initial Redis cache write).
- QR session budget cap on cache-miss rebuild.
- Final billing budget cap (over-consumption clamp).
- Over-payment refund formula (`amount_paid - energy_cost - gst_amount - synthetic_fee`).
- `GSTInvoice.gateway_charges` and `gateway_gst` snapshot at invoice issuance.

The zero-energy refund site is out of scope here (covered by issue 01).

Add a startup-time log line in `main.py` showing the configured `RAZORPAY_PLATFORM_FEE_PERCENT` value. If the env var is missing or resolves to zero, log an error and fail the startup loud (per CLAUDE.md env-var checklist).

See [ADR 0001](../../../docs/adr/0001-synthetic-vs-actual-platform-fee.md) and [CONTEXT.md](../../../CONTEXT.md) for terminology and rationale.

## Acceptance criteria

- [ ] `_resolve_platform_fee` no longer exists in the QR payment service; replaced by the two new helpers above.
- [ ] All budget-cap call sites read the synthetic value; none read from the QRPayment row's stored fee fields.
- [ ] `GSTInvoice.gateway_charges` equals `amount_paid × 2/118` (rounded to 2 dp) and `gateway_gst` equals `amount_paid × 2 × 18/118` for every newly-issued invoice on a QR session.
- [ ] `QRPayment.platform_fee` on a newly-completed session still reflects Razorpay's actual webhook fee — verified by an integration test that mocks the webhook fee to a non-2% value (e.g. 1.7%) and asserts the QRPayment row stores 1.7% while the invoice and budget use 2%.
- [ ] Over-payment refund on a partial-consumption session computes refund using the synthetic fee, not the actual.
- [ ] Backend startup logs `RAZORPAY_PLATFORM_FEE_PERCENT=<value>` and refuses to start if the value is missing, zero, or negative.
- [ ] Unit tests for both helpers, including the commission/GST split arithmetic.
- [ ] Integration test runs a full QR session with a mocked actual fee of 1.5% and an `amount_paid` of ₹500: asserts QRPayment.platform_fee ≈ ₹7.50, invoice gateway_charges = ₹8.4746, invoice gateway_gst = ₹1.5254, budget kWh consistent with 2% deduction.
- [ ] Existing tests pass (excluding documented baseline flakes).

## Blocked by

None — can start immediately (independent code path from issue 01; both touch `qr_payment_service.py` so coordinate merge order to avoid conflicts).
