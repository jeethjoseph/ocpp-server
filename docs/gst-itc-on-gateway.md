# GST: ITC on Razorpay gateway tax

## TL;DR for the CA

VoltLync's invoice-level `total_tax` is computed as the literal sum of two
separately-determined amounts:

- `energy_tax` — 18% applied to the energy charge at our tariff rate.
- `gateway_tax` — the exact GST amount Razorpay charges on its commission,
  sourced verbatim from Razorpay's webhook (`qr_payment.razorpay_gst`).
  Our code does **not** assume the gateway tax rate; if Razorpay's effective
  rate ever differs from 18%, the invoice still reflects Razorpay's number.

The gateway portion is also remitted to the government independently by
Razorpay under their own GSTIN (Razorpay issues VoltLync a tax invoice
each month for its commission + GST).

To avoid the same gateway tax being paid to the government twice — once by
Razorpay on its commission, once by VoltLync as part of our output GST —
**VoltLync's finance team must claim Input Tax Credit (ITC) on the gateway
tax every GSTR-3B cycle**, against Razorpay's monthly tax invoice to
VoltLync.

## Where the data lives

- `gst_invoice.gateway_charges` — pre-tax Razorpay commission for the
  session (snapshotted from `qr_payment.razorpay_commission`).
- `gst_invoice.gateway_gst` — GST charged by Razorpay on that commission
  (snapshotted verbatim from `qr_payment.razorpay_gst`). **NULL** for
  wallet sessions (no gateway leg).
- Both columns are included in the admin CSV export
  (`/api/admin/invoices/export.csv`) for monthly reconciliation against
  Razorpay's tax invoice.

## Monthly process

1. Pull the admin GST invoice CSV for the filing month, filtered to
   `series=QR`.
2. Sum `gateway_gst` across all rows — this is the total input GST on
   gateway services for the month.
3. Cross-check against Razorpay's monthly tax invoice to VoltLync (line
   item: GST on platform fees). The two totals should match within paise
   rounding.
4. Claim the matched sum as ITC on the GSTR-3B "Inward supplies" section.

## Why the column exists

Before migration 30, `gateway_gst` was only stored on `qr_payment`, which
made monthly reconciliation require a join back from `gst_invoice` to
`qr_payment` to assemble the filing dataset. With the snapshot column on
the invoice row itself, the CSV export is a single source of truth.
