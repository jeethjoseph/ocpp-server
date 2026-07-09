# 02 — Reconcile already-issued orphaned invoices for fully-refunded sessions

Status: wontfix (2026-07-09 — leave as-is; see FINDINGS.md §5)

## What to build

Issue 01 stops *new* orphaned invoices, but invoices already issued in staging
and prod for fully-refunded / non-billed sessions (invoice 61 and its siblings)
remain — real, sequential invoice numbers asserting a phantom taxable supply for
money that was returned to the customer. These need a compliance-aware cleanup.

Two parts:

1. **Find affected rows (AFK).** A read-only query over `GSTInvoice` joined to
   `Transaction` / `QRPayment` identifying invoices where the linked session is
   net-zero-retained (`amount_paid - refund_amount <= 0` for QR, or
   `total_billed <= 0` / `energy_charge <= 0`). Run it against staging and prod
   via the standard SSM path; produce a list with invoice number, txn id,
   amount_paid, refund_amount, total_amount.

2. **Decide and apply the remediation (HITL — GST decision).** Choose per
   compliance whether to **void**, issue a **credit note**, or **leave +
   annotate** each affected invoice. GST invoice numbers are sequential and
   already consumed, so voiding vs credit-note has filing implications (GSTR-1) —
   this is a human call, not an agent default.

HITL because the remediation is a tax-compliance decision on live prod data.

## Acceptance criteria

- [ ] A read-only query lists all net-zero-retained invoices in staging and prod with the key columns
- [ ] The remediation approach (void / credit note / annotate) is decided and recorded on this issue
- [ ] The chosen remediation is applied to the identified staging and prod rows
- [ ] GSTR-1 / filing impact of the chosen approach is noted for the accountant
- [ ] No invoice-number sequence gaps are introduced silently — any gap or void is documented

## Blocked by

- 01 — Suppress GST invoice issuance when net amount retained is zero

## Comments

### Affected-invoice query run 2026-07-09 (read-only, via SSM)

Query: `gst_invoice` LEFT JOIN `qr_payment` / `transaction`, flagging rows where
QR `amount_paid - refund_amount <= 0`, or wallet `total_billed <= 0`.

**PROD — 2 rows:**

| invoice_number | txn | total_amount | amount_paid | refund | net | status | kWh | note |
|---|---|---|---|---|---|---|---|---|
| VL/F1/QR/202627/00007 | 831 | 5.00 | 250.00 | 250.00 | 0 | REFUNDED / COMPLETED | **26.462** | ⚠️ large real session fully refunded, energy_charge NULL |
| VL/F3/QR/202627/00061 | 1027 | 1.00 | 50.00 | 50.00 | 0 | REFUNDED / COMPLETED | 0.188 | the reported invoice 61 |

**STAGING — 11 rows:** 3 QR fully-refunded (VL/F5/QR 00367/00369/00370, ~0.2 kWh,
₹0.10 each) + 8 WAL zero/BILLING_FAILED (total_amount 0.00, wallet sessions with
`total_billed` NULL; txns 66/81/86/129/130/132/139/153).

Two structural classes among the orphans:
1. **QR fully-refunded** — non-zero `total_amount` = synthetic gateway line only
   (2% of amount_paid, ADR 0001); asserts a phantom taxable supply and consumed a
   real sequential invoice number. (F1/00007, F3/00061, F5 QR trio.)
2. **WAL zero-value / BILLING_FAILED** — `total_amount` 0.00; wallet sessions
   whose billing never completed. Zero-value but still consumed an invoice number.

Both are net-zero-retained and would be suppressed by the issue-01 guard going
forward. Remediation (void vs credit note vs annotate) is still the pending
compliance decision below.

**Flag beyond this issue:** prod txn 831 delivered **26.462 kWh** on a COMPLETED
session yet was fully refunded (₹250) with `energy_charge` NULL — that is real
energy given away, a likely revenue-loss bug distinct from invoice cleanup.
Warrants its own RCA (why a completed multi-kWh session fully refunded without a
billing breakdown).
