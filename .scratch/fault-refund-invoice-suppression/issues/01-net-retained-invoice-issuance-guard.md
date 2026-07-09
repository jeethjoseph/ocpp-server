# 01 — Suppress GST invoice issuance when net amount retained is zero

Status: done

## What to build

`InvoiceService.generate_invoice` currently issues a GST invoice whenever the
session's *metered* energy (`energy_consumed_kwh`) is > 0. That lets a
**fully-refunded, non-billed session** produce a tax invoice — most visibly the
ADR 0013 fault-refund band (a `FAILED` session with
`0 < energy < MIN_BILLABLE_ENERGY_KWH`, refunded in full, whose billing
breakdown is never written so `energy_charge` stays 0). The resulting invoice
asserts a taxable supply (the synthetic gateway line + GST, ADR 0001) that was
in fact returned to the customer, and it breaks the prepaid invariant
`total_amount + refund_amount == amount_paid` (invoice 61 /
`VL/F3/QR/202627/00061`: `1.00 + 50 ≠ 50`).

Replace the issuance guard with a **net-retained** check — issue an invoice only
when the customer was left out of pocket by more than zero:

- **QR sessions** (a linked `QRPayment` exists): suppress when
  `amount_paid - refund_amount <= 0`. This is stricter than gating on
  `energy_charge` alone — it also suppresses invoices for **manual/goodwill full
  refunds of otherwise-billed sessions**, where energy was billed but the whole
  payment was later returned.
- **Wallet sessions** (no `QRPayment`): suppress when `total_billed <= 0`.

Note: the `QRPayment` row is currently fetched partway through the function,
after the metered-energy guard and the charger/station lookups — the net-retained
check needs it earlier, so the fetch (or the guard placement) must move so the
check runs before any invoice-number is consumed. Keep the existing
`energy_consumed_kwh <= 0` short-circuit as well (zero-energy sessions never
invoice). An interim `energy_charge <= 0` guard is already present in the working
tree; this issue supersedes it with the net-retained form. Emit the existing
`Custom/Invoice/NonBillableSkipped` metric on suppression. Keep functions under
40 lines.

## Acceptance criteria

- [ ] A `FAILED` QR session with `0 < energy < MIN_BILLABLE_ENERGY_KWH` and a full refund produces **no** `GSTInvoice` row (reproduces invoice 61)
- [ ] A QR session that billed energy but was later **fully refunded** (`refund_amount == amount_paid`) produces no invoice — the case the net-retained form adds over the interim `energy_charge` guard
- [ ] A normal partially-refunded QR session (net retained > 0) still issues an invoice, and `total_amount + refund_amount == amount_paid` holds
- [ ] A wallet session with `total_billed <= 0` produces no invoice; a normal wallet session still does
- [ ] Zero-energy sessions still short-circuit before any lookups; no invoice number is consumed for any suppressed session
- [ ] `Custom/Invoice/NonBillableSkipped` is incremented on suppression
- [ ] Idempotency is unaffected — re-calling `generate_invoice` on a suppressed session still returns `None` and creates nothing
- [ ] Per-file pytest (`tests/test_invoice_service.py`) covers all the above cases

## Blocked by

- None - can start immediately

## Comments

- Implemented 2026-07-09. `generate_invoice` now fetches the `QRPayment` row
  early and gates issuance on net retained: QR → `amount_paid - refund_amount`,
  wallet → `total_billed`; suppresses (returns None, increments
  `Custom/Invoice/NonBillableSkipped`) when `<= 0`. The interim `energy_charge`
  guard was replaced. Redundant later QRPayment fetch removed.
- Tests in `tests/test_invoice_service.py`: fault-refund band (invoice 61),
  goodwill full-refund of a billed session, wallet zero-billed, and a
  partial-refund guardrail that still issues. Full file 24 passed; adjacent
  QR/refund/PDF/wallet suites 142 passed.
