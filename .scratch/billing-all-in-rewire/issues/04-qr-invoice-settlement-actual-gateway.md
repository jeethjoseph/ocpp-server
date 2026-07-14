# QR invoice + settlement → actual gateway line

Status: ready-for-agent

## What to build

Make the GST Invoice and the franchisee settlement ledger use the actual gateway fee, matching the billing/refund from slice 03 (ADR 0026). In `invoice_service`, the gateway line (`gateway_charges`/`gateway_gst`) is sourced from the stored actual fee on the QRPayment row instead of `synthetic_fee_split(amount_paid)`; the header snapshot writes `rate_gst_included`; the energy line continues to read `txn.energy_charge`/`gst_amount`. In `franchisee_settlement_service`, `pg_fee_amount` becomes the actual gateway (`razorpay_commission + razorpay_gst`) instead of the synthetic figure. Because the gateway is now added to the customer bill and subtracted in both refund and `pg_fee`, it cancels out of the franchisee's payout — the franchisee's pool equals `energy_kwh × base_rate`, independent of Razorpay's fee. This reverses ADR 0001's 2026-05-29 synthetic-ledger amendment (safe precisely because the fee cancels). The ADR 0023 net-retained guard stays as-is (still valid, now never triggered by a clamp since no clamp exists). Wallet gateway stays 0.

## Acceptance criteria

- [ ] Invoice gateway line = stored actual fee; `total_amount + refund_amount == amount_paid` holds for QR
- [ ] Invoice header snapshot column written as `rate_gst_included`; energy line unchanged; historical invoices re-render from stored fields unchanged
- [ ] Settlement `pg_fee_amount` = actual gateway (QR); wallet `pg_fee = 0` unchanged
- [ ] `commission_ledger_entry.net_excl_gst == energy_kwh × base_rate` (== invoice energy_taxable_value); franchisee payout independent of gateway value
- [ ] ADR 0001 synthetic-ledger amendment reversal noted in the ledger code comment pointing to ADR 0026
- [ ] Per-file pytest green: invoice reconciliation, settlement math, franchisee-pool gateway-independence

## Blocked by

- 03-qr-billing-energy-from-base-rate-actual-gateway.md
