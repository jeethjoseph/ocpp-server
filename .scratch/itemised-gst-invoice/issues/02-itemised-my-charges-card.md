# 02 — Itemised /my-charges receipt card (line items + totals)

Status: done (commit 92c010c)

## What to build

Reshape the `/my-charges` receipt card from the flat `Energy cost / GST / Gateway
fee` breakdown to itemised **line items + Total**, per
`docs/adr/0024-itemised-gst-invoice-layout.md`.

The customer-facing breakdown endpoint (`_customer_breakdown`, feeding the card)
returns per-line **tax-inclusive line totals** — Energy and Gateway charges — plus
a Total, reusing the shared tax-allocation helper from issue 01 (so the card's
numbers match the PDF's Line total column exactly). The card renders:

- **Energy** — its tax-inclusive line total
- **Gateway charges** — its tax-inclusive line total (omitted for wallet sessions)
- **Total** — `amount_paid − refund` (what the customer netted)

No per-line SGST/CGST split on the card (mobile width) — one amount per line. The
existing Paid / refund rows stay. Must keep reconciling: sum of line totals +
round-off residual == Total == `amount_paid − refund`.

## Acceptance criteria

- [ ] `_customer_breakdown` returns per-line tax-inclusive line totals (Energy, Gateway) + Total, reusing issue 01's allocation helper
- [ ] The card shows Energy and Gateway line items with tax-inclusive amounts, plus a Total row
- [ ] Wallet sessions show a single Energy line + Total (no gateway line)
- [ ] Line totals + any round-off reconcile to Total == `amount_paid − refund`, matching the PDF
- [ ] Card numbers match the PDF's Line total column for the same session
- [ ] `cd frontend && npm run build` passes; per-file backend pytest for the public QR transaction suites passes

## Blocked by

- 01 — Itemised GST invoice PDF (per-line-item table)
