# 01 — Accurate energy on the bill + make the receipt card match the bill

Status: ready-for-agent

## What to build

A QR charging session is shown to the customer on two surfaces that currently disagree: the **GST invoice (PDF)** and the **My Charges receipt card**. The invoice is the reconciled source of truth (its total equals amount paid − refund, to the paisa); the card is not. Also, both round the energy quantity, hiding the real value. Fix both so the customer sees one consistent, accurate story.

### A. Show accurate energy (no rounding)

`energy_consumed_kwh` is stored to 3 decimals but the invoice PDF renders it at 1 decimal (`:.1f`), so **3.065 kWh prints as "3.1"**. Show the stored value at full precision (3 dp) on the invoice, and the same value on the card. Do not change any billing math — only the displayed quantity. (Note the invoice stores `billable_kwh`, which can legitimately differ from the raw meter delta; show whatever the invoice stored, unrounded.)

### B. Make the receipt card match the invoice

The card is fed directly from the `qr_payment` row, which carries the wrong numbers for customer display:
- **Fee:** the card shows `qr_payment.platform_fee` = the **actual Razorpay commission** (e.g. ₹1.17). Per ADR 0001 the real Razorpay fee is ops/reconciliation-only and must **never** be customer-facing. The customer was charged the **synthetic gateway fee** (2% of the prepaid amount, e.g. ₹2.00 = ₹1.69 taxable + ₹0.31 GST) — that is what the invoice shows and what the card must show.
- **GST:** the card shows GST on energy only (e.g. ₹11.46). The invoice charges GST on energy **+ gateway** (e.g. ₹11.77). Card must match the invoice.
- **Total:** the card's line items sum to less than the customer actually paid (e.g. 63.64 + 11.46 + 1.17 = 76.27, but the customer paid 100 − 22.90 = **77.10**). Card must reconcile to amount paid − refund, exactly like the invoice total.

The card must present the **same reconciled breakdown as the GST invoice** for the same session. Preferred implementation: source the card's amounts from the `gst_invoice` (the reconciled source of truth), or compute them identically to `invoice_service`. Stop reading `qr_payment.platform_fee` / `qr_payment.gst_amount` for customer display.

## Acceptance criteria

- [ ] Invoice PDF shows `energy_consumed_kwh` at full stored precision (e.g. `3.065`), not `3.1`.
- [ ] The receipt card shows the identical energy value as the invoice.
- [ ] The card's fee line equals the invoice's synthetic gateway fee (gateway taxable + gateway GST), **not** the actual Razorpay commission.
- [ ] The card's GST equals the invoice's total tax (energy + gateway), not energy-only.
- [ ] The card's total equals `amount_paid − refund_amount`, equals the invoice `total_amount`, and the card's line items sum to that total.
- [ ] No customer-facing surface reads `qr_payment.platform_fee` (ADR 0001).
- [ ] Verified against the reference session (invoice `VL/F5/QR/202627/00114`, txn 527 on staging): both surfaces show **Energy 3.065 kWh · Energy 63.64 · Gateway 1.69 · GST 11.77 · Total 77.10 · Refund 22.90** — card and PDF identical.
- [ ] Backend per-file pytest for the card/invoice endpoints green (baseline flakes excepted per CLAUDE.md); `cd frontend && npm run build` passes.

## Notes / out of scope

- This issue is **display consistency only** — do not change the pricing model. The separate question of whether the 2% gateway should be charged on consumption vs the prepaid amount (so that `energy × tariff = total`) is a commercial decision tracked elsewhere; leave the charge math as-is here.
- Rounding-safety: when sourcing the card from the invoice, use the invoice's stored amounts directly rather than re-deriving, so the two can never drift by a paisa.

## Blocked by

None - can start immediately.

## Comments

**2026-07-03 — implemented.**
- **Bill:** `invoice_service.py` now renders `energy_consumed_kwh` at `:.3f` (3.065, was `:.1f`→3.1). No billing-math change.
- **Card:** the public `/api/public/qr-transactions` endpoint now sources the breakdown from the reconciled `gst_invoice` (via `_customer_breakdown`) — `energy_cost = energy_taxable_value`, `gateway_fee = gateway_charges`, `gst_amount = total_tax` — falling back to the synthetic split (`synthetic_fee_split`) when no invoice exists. Dropped `platform_fee` (the real Razorpay commission), `razorpay_commission`, `razorpay_gst`, `fee_source` from the customer response (ADR 0001). Frontend `QRTransactionItem` + `TransactionCard` updated: energy shown at `toFixed(3)`, fee line relabelled "Gateway fee" from the reconciled `gateway_fee`. Admin qr-codes ops view untouched (correctly still shows the real fee).
- **Reconciliation:** `energy_cost + gateway_fee + gst_amount == amount_paid − refund`, identical to the PDF. Verified for the reference case (₹63.64 + ₹1.69 + ₹11.77 = ₹77.10 = 100 − 22.90).
- Tests: `tests/test_qr_receipt_card_breakdown.py` (4) + existing `test_public_qr_transactions.py` (3) green; `test_invoice_service.py` (20) green. `npm run build` passes.
