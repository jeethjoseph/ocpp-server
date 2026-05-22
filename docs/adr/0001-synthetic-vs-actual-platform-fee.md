# Use a fixed synthetic 2% platform fee for billing math; capture the actual Razorpay fee separately for ops

Razorpay's platform fee on UPI payments varies in practice (typically 0–2%, sometimes higher depending on the instrument and Razorpay's pricing of the moment). We previously fed the webhook-captured **actual** fee into both the QR-session budget cap and the GST invoice's gateway-charges line, which meant the per-kWh price a customer effectively paid wobbled with Razorpay's daily pricing. We now use a fixed percentage (default 2%, env var `RAZORPAY_PLATFORM_FEE_PERCENT`) — the **synthetic platform fee** — for every customer-facing calculation: budget cap, over-payment refund, and invoice gateway-charges line. The real webhook fee continues to land on the `QRPayment` row (`platform_fee`, `razorpay_commission`, `razorpay_gst`) and is used only for reconciliation, ops dashboards, and the nightly drift detector. The variance between the two — sometimes positive, sometimes negative — is absorbed by VoltLync's P&L.

The 2% is treated as all-in: commission = `× 2/118`, GST on commission = `× 2 × 18/118`. This matches the existing fee-estimator convention in `_resolve_platform_fee` and lets future maintainers see one consistent split everywhere.

## Considered alternatives

- **Stack 18% GST on top of 2%** (effective 2.36%). Rejected: would inflate every customer-facing all-in price by another 0.36% with no clear gain in GST-correctness, since the all-in interpretation is equally defensible under CGST.
- **Drop the GST split on the invoice's gateway line.** Rejected: Razorpay's commission is a taxable service in our hands and ignoring its GST muddies our ITC claim.
- **Keep using the actual webhook fee.** Rejected: customers cannot be told "your per-kWh rate is X" if X drifts with Razorpay's invisible pricing decisions.

## Consequences

- Invoices and budget math are deterministic from `amount_paid` alone — no Razorpay webhook needed at calculation time.
- The "actual − synthetic" variance becomes a queryable P&L line. A persistent positive variance (Razorpay charging more than 2%) is a signal to renegotiate or raise the synthetic figure.
- The drift detector (`backend/scripts/reconcile_wallet_balance.py` pattern) should be extended to flag chronic actual > synthetic.
