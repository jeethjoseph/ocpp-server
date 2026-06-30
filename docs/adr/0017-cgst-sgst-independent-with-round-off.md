# CGST and SGST are computed independently (equal halves) with a Round Off line

Status: accepted

On an intra-state **GST Invoice**, CGST and SGST are each computed **independently** from the taxable value at half the GST rate (9% each for an 18% tariff), so they always come out **equal**. The sub-rupee difference between `CGST + SGST` and the billing tax that the invoice total must reconcile to is carried as an explicit **Round Off** line on the invoice, not absorbed into an asymmetric SGST. Inter-state invoices (single IGST component) are unaffected and carry `round_off = 0`.

## Why

Earlier, `determine_gst_split` computed one `total_tax = energy_tax + gateway_tax` and then **halved** it: `cgst = round(total_tax / 2)`, `sgst = total_tax − cgst`. SGST absorbed the 1-paisa rounding residual, so the two halves were unequal (observed on prod invoice `VL/F1/QR/202627/00042`: CGST ₹112.77, SGST ₹112.76).

Under GST law CGST and SGST are **two separate levies under two separate Acts**, each computed directly from the taxable value at its own rate. Section 170 / Rule 51 round each *component*, and you build the total up from the components — not the other way round. Because both use the same base and rate, the legally-correct values are **identical**. Halving a pre-summed total is the anti-pattern: it manufactures an asymmetry that does not exist in law, and — at scale — cumulative paisa mismatches can flag during GSTR-1 / GSTR-2B reconciliation, where the portal *recomputes* `taxable × rate` and expects it to match each reported component.

The catch specific to our system: the invoice's `total_amount` must reconcile **exactly** to the payment — for QR sessions `total_amount = amount_paid − refund`, and the refund is derived in `qr_payment_service` from a separately-rounded billing tax (`energy_tax + gateway_tax`), not from the invoice's tax components. Computing CGST and SGST independently shifts their sum by a paisa relative to that billing tax, which would break `billed + refund = amount_paid`. The **Round Off** line resolves this: `total_amount` stays anchored to the billing tax (untouched, still reconciles with the refund), and the residual between the legally-independent component tax and the billing tax lives in `round_off`. This is the standard Tally/Zoho/Marg behaviour — components are authoritative, the grand total carries a "Round Off" adjustment.

Concretely, for `VL/F1/QR/202627/00042` (total taxable ₹1252.91):

| | Before | After |
|---|---|---|
| CGST | 112.77 | **112.76** |
| SGST | 112.76 | **112.76** (equal) |
| `total_tax` (= CGST+SGST) | 225.53 | 225.52 |
| Round Off | — | **+0.01** |
| `total_amount` | 1478.44 | 1478.44 (unchanged) |
| Refund | 21.56 | 21.56 (unchanged) |

## Design

- The reconciling identity is preserved: `total_taxable + total_tax + round_off == energy_taxable + gateway_taxable + energy_tax + gateway_tax`, i.e. `round_off = (energy_tax + gateway_tax) − (cgst + sgst)`. Therefore `total_amount` is unchanged and the refund path is **not touched**.
- `round_off` is a new nullable-default `DecimalField` on `GSTInvoice` (migration adds the column, default `0`). It is reported on the PDF only when non-zero.
- Round-off is **paisa-level**, not nearest-rupee (see rejected option) — it absorbs only the component-rounding residual (typically ±0.01, at most ±0.02 when both energy and gateway lines round adversely), so the customer's refund and the printed total never move by more than the residual that already existed inside the asymmetric SGST.
- Inter-state path is left exactly as-is: `igst_amount = total_tax`, `round_off = 0`. IGST is a single component, so the asymmetry problem cannot arise there.
- **No backfill.** Historical invoices are immutable legal documents; they keep their stored (asymmetric) split and `round_off = 0`. Only invoices issued after this change use independent halves. This interacts with [[adr-0001-synthetic-vs-actual-platform-fee]] (gateway line still uses the synthetic 2% split) and [[adr-0003]] (all-in tariff decomposition) — neither changes.

## Considered options

- **Independent components + paisa-level Round Off (chosen).** Legally-correct equal CGST/SGST, GSTR-1-recompute-clean, and `total_amount`/refund reconcile to the paisa via the Round Off line. One additive column, no refund changes, no backfill.
- **Independent components + nearest-rupee Round Off (rejected).** Strict Section 170 rounds the grand total to the nearest rupee (e.g. ₹1478.43 → ₹1478.00, Round Off −0.43). Cleaner-looking total, but it moves the customer's refund by up to ~₹0.50 per session and requires re-deriving the refund from the invoice total — coupling two subsystems that are currently independent. Not worth the blast radius for a prepaid-refund flow where every paisa is returned.
- **Keep halving the total (status quo, rejected).** Reconciles to the total but yields asymmetric CGST≠SGST that misrepresents two equal statutory levies and risks GSTR-1 recompute mismatches at scale.
- **Re-derive the refund from the invoice components (rejected).** Would let the invoice be the single source of truth for tax, but inverts the dependency (billing currently leads, invoicing follows) and would re-open the settled refund math. The Round Off line achieves reconciliation without that coupling.
