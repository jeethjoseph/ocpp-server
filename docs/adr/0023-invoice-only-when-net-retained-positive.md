# A GST invoice is issued only when the net amount retained is positive

`InvoiceService.generate_invoice` issues a tax invoice only when the customer was
left out of pocket by a positive amount. Concretely, after the zero-energy
short-circuit it gates on the **net amount retained**:

- **QR sessions** (a linked `QRPayment` exists): suppress issuance when
  `amount_paid - refund_amount ≤ 0`.
- **Wallet sessions** (no `QRPayment`): suppress issuance when `total_billed ≤ 0`.

A suppressed session returns `None`, consumes no invoice number, and increments
`Custom/Invoice/NonBillableSkipped`.

## The bug this fixes

`generate_invoice` previously gated only on **metered** energy
(`energy_consumed_kwh > 0`). That let a **fully-refunded, non-billed** session
still produce an invoice — most visibly the ADR 0013 fault-refund band (a `FAILED`
session delivering `0 < energy < MIN_BILLABLE_ENERGY_KWH`, refunded in full, whose
billing breakdown is never written so `energy_charge` stays 0). Metered energy was
> 0, so the guard passed and an invoice was issued whose only content was the
synthetic 2% gateway line + GST (ADR 0001) — a fee that was itself refunded.

Observed in production as invoice `VL/F3/QR/202627/00061`: customer paid ₹50, was
refunded the entire ₹50, yet received a tax invoice with **TOTAL ₹1.00**. That
invoice asserts a taxable supply that did not occur and breaks the prepaid
invariant `total_amount + refund_amount == amount_paid` (`1.00 + 50 ≠ 50`).

## Why net-retained, not `energy_charge`

Gating on `energy_charge > 0` alone would close the fault-refund band, but the
**net-retained** rule is strictly stronger: it also suppresses invoices for a
session that *did* bill energy but was later **fully refunded** (e.g. a goodwill /
manual refund), where `energy_charge > 0` but the customer got everything back.
The invariant "an invoice exists iff the customer was net-charged" is the property
we actually want, and net-retained states it directly.

This generalizes the principle ADR 0002 established for the `energy ≤ 0` case
("no taxable supply → no invoice") to every full-refund path, regardless of how
the session reached a full refund (fault-refund band, zero-energy, disconnect,
manual). The `QRPayment` row is fetched before the guard so no invoice number is
consumed for a suppressed session, keeping the per-(franchisee, series, FY)
sequence clean — the same discipline as the internal-role skip (ADR 0004).

## Considered alternatives

- **Gate on `energy_charge > 0`.** Rejected: closes the fault-refund band but not
  the fully-refunded-billed-session case. Net-retained subsumes it.
- **Keep the metered-energy guard and issue a zero/near-zero invoice.** Rejected:
  it asserts a phantom taxable supply, burns a sequential GST number, and violates
  the prepaid invariant. (ADR 0002 already rejected zero-value invoices under CGST
  Rule 46.)
- **Void/credit-note after issuance instead of suppressing at source.** Rejected as
  the primary mechanism: cleaning up consumed GST numbers carries GSTR-1 handling
  cost. Suppression at issuance is cheaper and leaves no artifact. (Remediation of
  invoices already issued before this rule is a separate, per-case compliance
  decision.)

## Consequences

- Fully-refunded sessions — via any path — no longer produce invoices. The refund
  itself and the `QRPayment` row remain the audit trail, as under ADR 0002.
- Invoices already issued before this rule (net-zero-retained) remain until
  separately remediated; they are a bounded historical set, not an ongoing leak.
- A session that is fully refunded but delivered **real** energy is a signal worth
  investigating on its own (energy given away for free) — the suppressed invoice is
  correct, but the underlying full refund of a substantive session may not be. This
  rule hides the symptom; it does not diagnose the refund.

## Related

- ADR 0002 — zero-energy full refund, no invoice (the principle this generalizes)
- ADR 0013 — de-minimis fault-refund band (`FAILED`, `0 < energy < 0.5 kWh`)
- ADR 0001 — synthetic vs actual gateway fee (what the phantom line was made of)
- ADR 0017 — CGST/SGST independent split with round-off
