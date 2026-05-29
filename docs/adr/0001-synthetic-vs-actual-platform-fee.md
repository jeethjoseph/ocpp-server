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

## Amendment — 2026-05-29: settlement ledger also uses synthetic

Originally the franchisee-settlement ledger (`commission_ledger_entry.pg_fee_amount`) was populated with the **actual** Razorpay commission + GST captured from `qr_payment.razorpay_commission + razorpay_gst`. That meant the customer-facing invoice and the franchisee-facing ledger disagreed on what was deducted as gateway fee — and disagreed on the resulting `net_excl_gst` revenue pool that commission, TDS, and payout are computed from. For ledger #97 on staging this produced a ₹0.19 mismatch between the invoice's `energy_taxable_value` (₹37.37) and the ledger's `net_excl_gst` (₹37.18).

The settlement engine now calls `synthetic_platform_fee(qr_payment.amount_paid)` to derive `pg_fee_amount`, so:

- `commission_ledger_entry.pg_fee_amount` equals `gst_invoice.gateway_charges + gateway_gst` for the same transaction.
- `commission_ledger_entry.net_excl_gst` equals `gst_invoice.energy_taxable_value` exactly (modulo a ₹0.01 quantize step in edge cases).
- Franchisee commission, TDS, and payout are computed against the synthetic-fee revenue pool — independent of Razorpay's instantaneous fee schedule.

### What changes for VoltLync

Variance absorption is no longer shared 75/25 between franchisee and platform. **VoltLync now absorbs 100% of the actual-vs-synthetic gap**, both upside (Razorpay charged < 2%) and downside (Razorpay charged > 2%). On the staging sample (111 QR payments), the cumulative drift is −₹46.51 (VoltLync favorable); the median actual fee is 1.72%; the worst per-session loss is +₹5.66 (Razorpay charged ₹5.66 more than synthetic). The ₹50–100 ticket bucket is the failure mode (median actual 2.42%, 71% of sessions over 2%) — if that bucket grows materially, revisit the synthetic % rather than reverting this amendment.

### What this means for drift detection

Before: drift was queryable directly from the ledger by comparing `pg_fee_amount` (actual) against `2% × gross_amount` (synthetic).

After: the ledger only contains synthetic. Drift queries must read `qr_payment.razorpay_commission + razorpay_gst` against `synthetic_platform_fee(qr_payment.amount_paid)` instead. Schema is unchanged; the source-of-truth shifts from `commission_ledger_entry` to `qr_payment`.

### Historical entries

Ledger entries created before 2026-05-29 still hold the actual fee in `pg_fee_amount`. There is **no backfill**: per-row reconciliation between the ledger and the bank statement is degraded for the pre-amendment slice, but it remains accurate for all post-amendment entries. Reports that span the cutover should be aware.

### Wallet sessions

Unchanged. `pg_fee = Decimal("0")` for wallet-funded sessions — top-up gateway fees are absorbed at top-up time, not per session (ADR 0002).
