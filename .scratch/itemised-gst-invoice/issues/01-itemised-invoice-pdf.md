# 01 — Itemised GST invoice PDF (per-line-item table)

Status: done

## Comments

- Done 2026-07-09. Added `build_invoice_line_items(invoice)` (shared, numeric,
  reused by issue 02) and rewrote `generate_pdf`'s table to HSN · Item · Rate ·
  Qty · SGST/CGST (or IGST) · Line total. Per-line tax is a display allocation of
  the stored totals (Energy = round(taxable×rate%), Gateway = remainder); Energy
  Rate derived as taxable÷qty. Charged-on/Duration moved to metadata; all-in
  tariff kept as a "quoted" note; footer Sub Total → Round Off → TOTAL. No schema
  change. Tests: intra allocation-sums-to-stored, inter-state IGST, wallet single
  line, PDF smoke for all three variants. Context docs updated. 77 passed across
  invoice/PDF/card/wallet suites.


## What to build

Redesign the GST Invoice PDF line-item table from the current
energy/tariff/amount layout to a per-line-item tax table, per
`docs/adr/0024-itemised-gst-invoice-layout.md`.

Columns: **HSN · Item · Rate · Qty · SGST · CGST · Line total**. For inter-state
invoices (`is_inter_state`), the SGST + CGST columns collapse into a single
**IGST** column. Two item rows:

- **Energy** — Rate = the GST-exclusive per-kWh figure, derived on the page as
  `energy_taxable_value ÷ energy_consumed_kwh` (equals `rate_per_kwh`; works for
  legacy invoices with no stored rate). Qty = `energy_consumed_kwh` at 3 dp.
- **Gateway charges** — Rate = the pre-tax gateway taxable value, Qty = 1. Omitted
  entirely for wallet sessions (no gateway).

Per-line tax is a **display allocation of the stored total-level tax** — ADR 0017's
computation is unchanged. Introduce a shared tax-allocation helper: the Energy line
takes `round(energy_taxable × rate%)` for each tax head and the Gateway line takes
`stored_total − energy_line`, so the columns always sum exactly to the stored
`cgst_amount` / `sgst_amount` / `igst_amount`. This helper is reused by issue 02.

Line total is tax-inclusive (`taxable + SGST + CGST`, or `+ IGST`). **Charged-on**
and **Duration** move out of the table into the invoice metadata block above it.
The footer keeps the subtotal → **Round Off** → **TOTAL** rows; the grand total is
still `total_taxable + total_tax + round_off = total_amount` (= `amount_paid −
refund` for QR). No schema change. Precision: Rate 2 dp, Qty 3 dp, tax 2 dp, Line
total 2 dp. Keep functions under 40 lines; extract the row-building and allocation
into helpers. Update `docs/v1/llm-context-document.md` and
`docs/v1/comprehensive-architecture-documentation.md` invoicing sections.

## Acceptance criteria

- [ ] The PDF line-item table renders HSN · Item · Rate · Qty · SGST · CGST · Line total, with Energy and Gateway rows
- [ ] Energy Rate = `energy_taxable_value ÷ energy_consumed_kwh`; Gateway Rate = gateway taxable, Qty 1
- [ ] Per-line SGST/CGST (or IGST) sum exactly to the stored total-level amounts, verified for a case where naive per-line rounding would drift a paisa
- [ ] Inter-state invoices show a single IGST column instead of SGST + CGST
- [ ] Wallet sessions (no gateway) render a single Energy line
- [ ] A legacy invoice (pre-redesign stored fields) renders correctly with a derived Rate
- [ ] Charged-on and Duration appear in the metadata block, not as table columns
- [ ] Footer still shows Round Off + TOTAL, and TOTAL == `amount_paid − refund` for QR
- [ ] Shared tax-allocation helper exists and is unit-tested (Energy exact, Gateway absorbs residual)
- [ ] `docs/v1/*` invoicing sections updated to describe the itemised layout
- [ ] Per-file backend pytest passes for the invoice suites

## Blocked by

- None - can start immediately
