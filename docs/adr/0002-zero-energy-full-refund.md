# A zero-energy QR session issues a full refund and no GST invoice

When a QR-funded charging session ends with `energy_consumed_kwh ≤ 0` (charger reports zero meter delivery), the customer is refunded the entire `amount_paid` — not `amount_paid - platform_fee` as previously. No GST invoice is issued, since no taxable supply occurred. Razorpay's actual processing fee on the original capture is still recorded on the `QRPayment` row for reconciliation, but VoltLync absorbs it (and any refund-processing fee) as P&L loss.

Rationale: a customer who paid and received nothing should be made whole. Deducting the gateway fee against a non-delivery is bad CX, treats the failure mode as if it were partial delivery (which it isn't), and the negative-NPS / social-media risk of "they kept ₹10 for nothing" costs more than the absorbed fee.

## Instant refund (2026-05-20 amendment)

All `_full_refund` flows — the six call sites that trigger a full refund (zero-energy at StopTransaction, stale payment, concurrent rejection, charger not connected, RemoteStart failure, plug-in timeout) — request Razorpay's `speed=optimum` mode so customers see the money back in minutes instead of 5–7 working days. VoltLync absorbs Razorpay's per-refund instant fee (~₹5–₹6 + 18% GST per UPI refund) in addition to the original capture fee.

Partial unused-credit refunds in `process_qr_session_billing` stay on Razorpay's default `normal` speed. The customer did receive service in the partial case; "here's your change" is not the same urgency as "we failed you."

`speed=optimum` is best-effort: Razorpay falls back to `normal` server-side when the payment method or rails don't support instant. The actual outcome is returned in `speed_processed` and logged on every refund.

Kill-switch: `RAZORPAY_INSTANT_REFUND_ENABLED` (default `true`). Flip to `false` and redeploy to revert all full refunds to normal speed without a code change — useful if Razorpay raises fees or instant rails get flaky.

## Instant-refund fallback diagnostics — float hypothesis disproven (2026-06-22 amendment)

Production showed `optimum` refunds silently downgrading to `normal` (e.g. QR payments #367/#368, two ₹500 full refunds). The **2026-06-18 amendment** added a best-effort funding-pool snapshot (`balance_before` / `refund_credits_before`, the Razorpay Account float and Refund Credits wallet) to the `QRRefundSpeed` event to test the working hypothesis that a thin settlement float was forcing the downgrade.

**The data refuted that hypothesis.** Across the captured snapshots, downgrades happened at the *highest* balances (₹1034–₹1231) while instant *succeeded* at the *lowest* (₹416–₹447); `refund_credits` was `0` in every case, including the instant successes. Balance is not the lever. The discriminator is the **customer's destination bank/VPA and its IMPS instant-refund support at that moment** — Razorpay's `optimum` is contractually "instant if the rail supports it, else fall back to normal", and the fallback is per-transaction. This was confirmed against Razorpay's own API: all sampled downgrades show `speed_requested=optimum` / `speed_processed=normal`, and the server logs show Razorpay returning `instant` synchronously then downgrading via the `refund.processed` webhook seconds-to-minutes later. Switching payment gateways would not help — every Indian gateway routes instant refunds over the same IMPS/UPI rails to the same banks, and the ~30–50% instant success rate proves the feature is enabled and working when the bank cooperates.

**Consequences for the code (2026-06-22):**
- The funding-pool snapshot (`RazorpayService.fetch_balance`, `_fetch_funding_pools`, `balance_before`/`refund_credits_before`) is **removed** — it answered its question.
- The creation-time `QRRefundSpeed` event and the `Custom/QR/RefundInstant{Succeeded,Fallback}` counters are **retired**. They were emitted at refund creation and captured Razorpay's *optimistic* synchronous `speed_processed` (≈always `instant`), so they under-counted the async downgrades.
- The instant-fulfilment ratio is now tracked from the authoritative terminal event: `OCPPMetrics.record_refund_final_speed`, called in `handle_refund_event` on `refund.processed`, emits the **`QRRefundFinalSpeed`** New Relic event with `speed_requested` + the final `speed_processed`. Track over time with:
  ```
  SELECT percentage(count(*), WHERE speed_processed = 'instant')
  FROM QRRefundFinalSpeed WHERE speed_requested = 'optimum'
  FACET appName TIMESERIES 1 day SINCE 30 days ago
  ```
- The remaining levers are product, not engineering: stop promising "instant" in customer copy (show "usually instant, up to 5–7 days depending on your bank"), and reconsider requesting `optimum` for sub-threshold refunds where the instant fee exceeds the benefit (ties into ADR 0013).

## Threshold widened to a half-unit (2026-06-20 — see ADR 0013)

The `energy ≤ 0` full-refund path is now reached by the broader `energy < 0.5 kWh` cliff (ADR 0013, **De-minimis Session**). **The "no taxable supply occurred" rationale below applies ONLY to the `energy ≤ 0` band and does not extend to the new `0 < energy < 0.5` band** — that band waives a *real* tiny supply as goodwill. Do not copy the non-supply reasoning onto de-minimis sessions; the audit/refund reason string is band-accurate for exactly this reason. The single `< 0.5` check subsumes the `≤ 0` check this ADR introduced.

## Considered alternatives

- **Keep deducting the gateway fee** (the pre-ADR behavior). Rejected: cost-recovery on failed service is the kind of policy customers screenshot and tweet about.
- **Issue a zero-value GST invoice** for audit-trail completeness. Rejected: invalid under CGST Rule 46 (no taxable value), and the `QRPayment` row already provides the audit trail.
- **Instant refunds for partial refunds too.** Rejected: partial = "here's your change" after service was rendered; the urgency case is failed-service refunds. Not worth the per-refund fee on every successful session.
- **Always instant, no kill-switch.** Rejected: a Razorpay fee change or rail outage with no flip-side would force a code-change deploy under pressure.

## Consequences

- A future contributor looking at `_full_refund` will see the actual platform fee captured on the row but ignored in the refund formula — this is intentional; see also ADR 0001.
- The "energy=0 absorbed loss" is queryable as `SUM(QRPayment.platform_fee WHERE refund_amount = amount_paid AND energy_consumed_kwh = 0)`. The instant-refund fee component is not stored on the `QRPayment` row — it is observable from the Razorpay dashboard / refund webhook and from the `speed_processed` log line emitted by `RazorpayService.refund_payment`.
