# A zero-energy QR session issues a full refund and no GST invoice

When a QR-funded charging session ends with `energy_consumed_kwh ≤ 0` (charger reports zero meter delivery), the customer is refunded the entire `amount_paid` — not `amount_paid - platform_fee` as previously. No GST invoice is issued, since no taxable supply occurred. Razorpay's actual processing fee on the original capture is still recorded on the `QRPayment` row for reconciliation, but VoltLync absorbs it (and any refund-processing fee) as P&L loss.

Rationale: a customer who paid and received nothing should be made whole. Deducting the gateway fee against a non-delivery is bad CX, treats the failure mode as if it were partial delivery (which it isn't), and the negative-NPS / social-media risk of "they kept ₹10 for nothing" costs more than the absorbed fee.

## Instant refund (2026-05-20 amendment)

All `_full_refund` flows — the six call sites that trigger a full refund (zero-energy at StopTransaction, stale payment, concurrent rejection, charger not connected, RemoteStart failure, plug-in timeout) — request Razorpay's `speed=optimum` mode so customers see the money back in minutes instead of 5–7 working days. VoltLync absorbs Razorpay's per-refund instant fee (~₹5–₹6 + 18% GST per UPI refund) in addition to the original capture fee.

Partial unused-credit refunds in `process_qr_session_billing` stay on Razorpay's default `normal` speed. The customer did receive service in the partial case; "here's your change" is not the same urgency as "we failed you."

`speed=optimum` is best-effort: Razorpay falls back to `normal` server-side when the payment method or rails don't support instant. The actual outcome is returned in `speed_processed` and logged on every refund.

Kill-switch: `RAZORPAY_INSTANT_REFUND_ENABLED` (default `true`). Flip to `false` and redeploy to revert all full refunds to normal speed without a code change — useful if Razorpay raises fees or instant rails get flaky.

## Considered alternatives

- **Keep deducting the gateway fee** (the pre-ADR behavior). Rejected: cost-recovery on failed service is the kind of policy customers screenshot and tweet about.
- **Issue a zero-value GST invoice** for audit-trail completeness. Rejected: invalid under CGST Rule 46 (no taxable value), and the `QRPayment` row already provides the audit trail.
- **Instant refunds for partial refunds too.** Rejected: partial = "here's your change" after service was rendered; the urgency case is failed-service refunds. Not worth the per-refund fee on every successful session.
- **Always instant, no kill-switch.** Rejected: a Razorpay fee change or rail outage with no flip-side would force a code-change deploy under pressure.

## Consequences

- A future contributor looking at `_full_refund` will see the actual platform fee captured on the row but ignored in the refund formula — this is intentional; see also ADR 0001.
- The "energy=0 absorbed loss" is queryable as `SUM(QRPayment.platform_fee WHERE refund_amount = amount_paid AND energy_consumed_kwh = 0)`. The instant-refund fee component is not stored on the `QRPayment` row — it is observable from the Razorpay dashboard / refund webhook and from the `speed_processed` log line emitted by `RazorpayService.refund_payment`.
