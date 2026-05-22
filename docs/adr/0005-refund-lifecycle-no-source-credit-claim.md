# Refund UI never claims "credited to your account" for normal refunds

The `/my-charges` transaction-card refund display renders a 3-state lifecycle (**Initiated** → **Sent to bank** → **Failed**) derived from `QRPayment.refund_processed_at` and `refund_failure_reason`. Wording for the terminal "Sent to bank" state is conditional on `razorpay_refund_speed_processed`:

- `"instant"` (UPI/IMPS): **"Refunded to your account on `<date>`"** — the rail is real-time, so `refund.processed` ≈ customer-side credit.
- `"normal"` (NEFT / card reversal): **"Sent to your bank on `<date>` — usually credits within 5–10 working days"**. We deliberately **do not** claim "credited" here.

Rationale: Razorpay's refund webhook surface has exactly four events — `refund.created`, `refund.processed`, `refund.failed`, `refund.speed_changed`. None of them signal that the customer's issuing bank has actually credited the source account; that handoff happens off-Razorpay and the issuing bank does not notify them when funds settle. `refund.processed` means "Razorpay has dispatched to the bank network", which for instant rails is effectively the same as "in customer account" but for normal rails is still days away from credit. Claiming "credited" on a normal refund would create a trust gap every time a customer doesn't see the money for a week.

## Considered alternatives

- **Poll Razorpay's Fetch Refund API to backfill `acquirer_data.arn` and surface the bank trace number.** Rejected: requires a recurring job (Razorpay populates the ARN minutes-to-hours after `refund.processed`), and customers who don't see their refund can already raise a support ticket — the ARN can be fetched on demand at that point rather than for every refund.
- **Claim "Refunded" uniformly regardless of speed, mirroring Razorpay's own dashboard copy.** Rejected: their dashboard is the merchant view; ours is the customer view. The wording asymmetry is the point.
- **Show only the refund amount and date, no lifecycle states.** Rejected: customers whose refund hasn't shown up have no way to distinguish "still in flight" from "Razorpay error" from "successfully sent days ago".

## Consequences

- The `refund.speed_changed` webhook **must** be handled, otherwise the "instant — minutes" wording can lie when Razorpay silently downgrades a refund to normal speed. The handler updates `razorpay_refund_speed_processed` on the row so the UI's ETA stays honest.
- If a future requirement demands a hard "credited" confirmation (e.g. for B2B contracts), we have to add the ARN-polling job + a separate UI state. The current schema (`QRPayment.razorpay_refund_id`, `refund_processed_at`, `razorpay_refund_speed_processed`, `refund_failure_reason`) is sufficient for the lifecycle described here; the ARN column would be additive.
- Support runbooks should treat "Sent to bank" + `speed_processed == "normal"` + complaint as a bank-trace request: pull the ARN from Razorpay dashboard on demand, hand it to the customer.
