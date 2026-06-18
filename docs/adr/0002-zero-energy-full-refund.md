# A zero-energy QR session issues a full refund and no GST invoice

When a QR-funded charging session ends with `energy_consumed_kwh ≤ 0` (charger reports zero meter delivery), the customer is refunded the entire `amount_paid` — not `amount_paid - platform_fee` as previously. No GST invoice is issued, since no taxable supply occurred. Razorpay's actual processing fee on the original capture is still recorded on the `QRPayment` row for reconciliation, but VoltLync absorbs it (and any refund-processing fee) as P&L loss.

Rationale: a customer who paid and received nothing should be made whole. Deducting the gateway fee against a non-delivery is bad CX, treats the failure mode as if it were partial delivery (which it isn't), and the negative-NPS / social-media risk of "they kept ₹10 for nothing" costs more than the absorbed fee.

## Instant refund (2026-05-20 amendment)

All `_full_refund` flows — the six call sites that trigger a full refund (zero-energy at StopTransaction, stale payment, concurrent rejection, charger not connected, RemoteStart failure, plug-in timeout) — request Razorpay's `speed=optimum` mode so customers see the money back in minutes instead of 5–7 working days. VoltLync absorbs Razorpay's per-refund instant fee (~₹5–₹6 + 18% GST per UPI refund) in addition to the original capture fee.

Partial unused-credit refunds in `process_qr_session_billing` stay on Razorpay's default `normal` speed. The customer did receive service in the partial case; "here's your change" is not the same urgency as "we failed you."

`speed=optimum` is best-effort: Razorpay falls back to `normal` server-side when the payment method or rails don't support instant. The actual outcome is returned in `speed_processed` and logged on every refund.

Kill-switch: `RAZORPAY_INSTANT_REFUND_ENABLED` (default `true`). Flip to `false` and redeploy to revert all full refunds to normal speed without a code change — useful if Razorpay raises fees or instant rails get flaky.

## Instant-refund fallback diagnostics (2026-06-18 amendment)

Production showed `optimum` refunds silently downgrading to `normal` (e.g. QR payments #367/#368, two ₹500 full refunds, both `speed_requested=optimum` / `speed_processed=normal`). Razorpay does not expose a downgrade reason on the refund object, so to diagnose it the `QRRefundSpeed` New Relic event (itself the 2026-05-20 amendment) is enriched with two fields captured **before** the refund POST, on `speed=optimum` refunds only:

- `balance_before` — the Razorpay primary **Account balance (Razorpay float)** in rupees.
- `refund_credits_before` — the **Refund Credits** wallet balance in rupees.

Working diagnosis: instant refunds are funded from the account float (or Refund Credits, if enabled). The account settles to bank frequently (near-daily), draining the float toward zero between sweeps, so a ₹300–₹500 refund often finds the float below the refund amount and Razorpay falls back to `normal`. Smaller refunds (≤₹100) clear because they fit the residual float. Refund Credits — a prepaid wallet that would decouple refunds from the settlement schedule — is **not enabled** on the account (`refund_credits=0`), so it currently provides no cushion. The fix is operational (enable + fund Refund Credits, or hold a settlement buffer), not a code change; this logging is to confirm the float hypothesis per-refund over time.

The balance fetch (`RazorpayService.fetch_balance`) is strictly best-effort: a 5s timeout, all errors swallowed to `None`, and the `QRRefundSpeed` event still fires with `balance_before=null` — the diagnostic must never degrade the refund itself. Note: `/v1/balance` returns a stale `updated_at`/null `last_fetched_at`, but the `balance`/`refund_credits` *values* are real-time (verified 2026-06-18 — the value moved ₹1,185 → ₹423 across a 25-min window); log the numbers, ignore those timestamp fields.

## Considered alternatives

- **Keep deducting the gateway fee** (the pre-ADR behavior). Rejected: cost-recovery on failed service is the kind of policy customers screenshot and tweet about.
- **Issue a zero-value GST invoice** for audit-trail completeness. Rejected: invalid under CGST Rule 46 (no taxable value), and the `QRPayment` row already provides the audit trail.
- **Instant refunds for partial refunds too.** Rejected: partial = "here's your change" after service was rendered; the urgency case is failed-service refunds. Not worth the per-refund fee on every successful session.
- **Always instant, no kill-switch.** Rejected: a Razorpay fee change or rail outage with no flip-side would force a code-change deploy under pressure.

## Consequences

- A future contributor looking at `_full_refund` will see the actual platform fee captured on the row but ignored in the refund formula — this is intentional; see also ADR 0001.
- The "energy=0 absorbed loss" is queryable as `SUM(QRPayment.platform_fee WHERE refund_amount = amount_paid AND energy_consumed_kwh = 0)`. The instant-refund fee component is not stored on the `QRPayment` row — it is observable from the Razorpay dashboard / refund webhook and from the `speed_processed` log line emitted by `RazorpayService.refund_payment`.
