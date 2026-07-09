# The GST invoice and receipt show a per-line-item table, with tax allocated for display only

The GST Invoice PDF renders a full-width line-item table with columns **HSN · Item · Rate · Qty · Taxable Value · SGST · CGST · Line total** (SGST+CGST collapse to a single **IGST** column for inter-state invoices). **Taxable Value** is the standard GST term for the pre-tax per-line amount, so every row reads `Taxable Value + SGST + CGST = Line total`. There are exactly two item rows: **Energy** and **Gateway charges**. The `/my-charges` receipt card shows the same two items as tax-inclusive line totals plus a Total.

Crucially, the per-line SGST/CGST are a **display allocation of the total-level tax**, not independently-computed per-line tax. ADR 0017's computation (CGST/SGST each an independent 9% of the *combined* taxable base, with a `round_off` residual) is unchanged; the invoice still stores only total-level tax. The renderer splits that total across the two lines so the columns sum exactly back to the stored `cgst_amount` / `sgst_amount` / `igst_amount`.

## Column semantics

- **Rate** (Energy) is the **GST- and gateway-exclusive** per-kWh figure — derived on the page as `energy_taxable_value ÷ energy_consumed_kwh`, which equals `rate_per_kwh`. It is *not* the customer-facing All-in tariff. With additive per-line tax columns and a separate gateway line, the pre-tax rate is the only value whose arithmetic closes (`Rate × Qty + SGST + CGST = Line total`); putting the all-in rate here would double-count the GST and gateway that are itemised elsewhere. This reverses the prior glossary rule that `rate_per_kwh` is "never shown to customers" — see CONTEXT.md. The All-in tariff remains the number shown on the QR/stations screens at pay time.
- **Rate** (Gateway) shows the flat percentage the gateway fee represents (e.g. `2%`), derived from the invoice's own synthetic split — `(gateway_charges + gateway_gst) ÷ transaction_amount × 100` — so legacy invoices keep their historical rate rather than picking up today's config. **Qty** (Gateway) is the **amount paid** (`transaction_amount`). This makes the gateway line read as "2% of ₹150" — more legible than a bare taxable value.
- **Line total** is tax-inclusive: `taxable + SGST + CGST` (or `+ IGST`).
- Consequence: the Rate column is deliberately **non-uniform**. For Energy, `Rate × Qty` is the *pre-tax* taxable (tax added by the columns); for Gateway, `Rate% × Qty` is the *tax-inclusive* line total (the synthetic 2% is all-in, so tax is already embedded). The `2% × paid` figure is a **nominal descriptor** — the authoritative gateway amount is the Line total, which can differ from `2% × paid` by the ADR-0017 allocation residual (visible only when there is a Round Off; nil in the common `round_off == 0` case).
- **Sub Total** is shown in the footer only when there is a **Round Off** to explain; when `round_off == 0` it would merely duplicate TOTAL, so it is omitted.
- **Charged-on** and **Duration** are session attributes, not line attributes — they move to the invoice metadata block above the table, not into the line columns.

## Tax allocation rule

For each tax head, the Energy line takes `round(energy_taxable × rate%)` and the Gateway line takes `stored_total − energy_line` — the residual always lands on the gateway line, so the two lines sum to the stored total to the paisa. The grand total remains `total_taxable + total_tax + round_off = total_amount` (= `amount_paid − refund` for QR), with **Round Off** and **TOTAL** shown in the footer beneath the line-item table.

## No schema change

Everything renders from fields already stored (`energy_taxable_value`, `gateway_charges`, `energy_consumed_kwh`, the total-level `cgst/sgst/igst_amount`, `round_off`). Legacy invoices re-render in the new layout correctly because Rate is derived, not stored. The `/my-charges` card gains per-line tax-inclusive totals computed by the same allocation in `_customer_breakdown`.

## Considered alternatives

- **Genuinely per-line computed tax** (each line rounded independently, totals = sum of lines). Rejected: it supersedes ADR 0017, needs new per-line tax columns (migration), and per-line rounding can shift the grand total by a paisa — which would ripple into the load-bearing prepaid reconciliation invariant `total_amount + refund_amount == amount_paid`. The display-only split gets the standard-looking itemised invoice without disturbing the settled tax/refund math.
- **Keep the All-in tariff in the Rate column.** Rejected: cannot coexist with additive SGST/CGST columns without double-counting; the arithmetic wouldn't close.
- **Always render SGST + CGST (drop IGST handling).** Rejected: produces a non-compliant document for inter-state (other-state franchisee charger) sessions.
- **Full itemised table on the mobile card.** Rejected: HSN/Rate/Qty/SGST/CGST is unreadable at phone width; the card shows tax-inclusive line totals + Total instead.

## Consequences

- The invoice Rate column exposes the pre-tax per-kWh figure (e.g. ₹20.76 for a ₹25 all-in tariff). This is intentional and consistent with CONTEXT's "the invoice shows the components" stance, but a customer comparing it to the ₹25 they were quoted needs the split explained — the itemised gateway line and tax columns account for the difference.
- A picky auditor recomputing a *single* line's tax in isolation may see a paisa difference from the allocation, because the authoritative rounding is at the total level (ADR 0017). The columns are guaranteed to sum correctly; they are not independently recomputable line-by-line. This is the accepted cost of not disturbing ADR 0017.
- Wallet invoices (no gateway) show a single Energy line; the card shows Energy + Total.

## Related

- ADR 0017 — CGST/SGST independent split with round-off (the total-level computation this presents)
- ADR 0001 — synthetic vs actual gateway fee (what the Gateway line is made of)
- ADR 0003 — all-inclusive tariff with operator absorption (the All-in tariff shown at pay time)
- ADR 0012 — invoice date IST issue basis
