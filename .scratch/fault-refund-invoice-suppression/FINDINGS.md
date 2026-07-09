# Fault-refund invoice suppression — investigation & decision record

**Date:** 2026-07-09
**Trigger:** Two customer bills (QR sessions) showed `ENERGY = 0` alongside a
non-zero cost / total. Reported invoices: `VL/F3/QR/202627/00060` and
`VL/F3/QR/202627/00061`.

---

## 1. Summary

Two separate defects surfaced from the reported bills:

1. **Display rounding (invoice 60)** — the PDF's "ENERGY BILLED (kWh)" column was
   formatted to **1 decimal**, so a real 0.02 kWh session rendered as `0.0` while
   the money line stayed non-zero. Cosmetic; the charge itself was correct.
2. **Orphaned invoice for a fully-refunded session (invoice 61)** — a session
   that was **fully refunded** still produced a tax invoice with a non-zero total.
   This is a correctness/compliance bug and is the substance of this record.

The invoice-issuance guard has been fixed (issue 01, done). The already-issued
orphaned invoices are being **left as-is** by decision (issue 02) — see §5.

---

## 2. Invoice 61 — what actually happened

- Session ended fully refunded: customer paid ₹50, got the entire ₹50 back.
- Yet a tax invoice was issued: **TOTAL ₹1.00** (energy ₹0.00 + synthetic gateway
  ₹0.85 + CGST ₹0.08 + SGST ₹0.08 − round-off ₹0.01).
- `energy_charge` on the transaction was **0** (the billing breakdown was never
  written), so the energy line printed ₹0.00 and the kWh column fell back to the
  raw metered 0.188 → "0.2".

The ₹1.00 is purely the synthetic 2% gateway fee (ADR 0001) computed off the ₹50
payment — a fee that was itself refunded. The invoice asserts a taxable supply
that did not occur, and it violates the prepaid invariant
`total_amount + refund_amount == amount_paid` (`1.00 + 50 ≠ 50`).

### Why the charge was zeroed

The session ended `FAILED` after delivering `0 < 0.188 < 0.5 kWh`, which lands in
the **ADR 0013 fault-refund band**: refund in full, skip writing the billing
breakdown. That behaviour is intended — the bug is that an invoice was issued
anyway.

### Why an invoice was issued

`InvoiceService.generate_invoice` gated issuance on **metered** energy
(`energy_consumed_kwh > 0`). 0.188 > 0, so it proceeded. The existing
`energy <= 0` guard protected the *zero-energy* full-refund case but not the
`0 < energy < 0.5` fault-refund band.

---

## 3. The fix (issue 01 — DONE)

`generate_invoice` now gates on the **net amount retained**, not metered energy:

- QR sessions: suppress when `amount_paid - refund_amount <= 0`
- Wallet sessions: suppress when `total_billed <= 0`

This is stricter than gating on `energy_charge` alone — it also suppresses
invoices for **goodwill/manual full refunds of otherwise-billed sessions**. The
`QRPayment` row is fetched early so the guard runs before any invoice number is
consumed; suppression logs and increments `Custom/Invoice/NonBillableSkipped`.

**Tests** (`backend/tests/test_invoice_service.py`): fault-refund band (invoice
61), goodwill full-refund of a billed session, wallet zero-billed, and a
partial-refund guardrail that still issues. Invoice suite 24 passed; adjacent
QR/refund/PDF/wallet/webhook suites 142 passed.

**Not committed yet** — lives in the working tree pending review/commit. The
separate `:.1f`→`:.3f` kWh-column display fix (invoice 60) is also uncommitted.

---

## 4. Audit of already-issued orphaned invoices

Read-only query on 2026-07-09 (via SSM, both RDS): `gst_invoice` LEFT JOIN
`qr_payment` / `transaction`, flagging QR `amount_paid - refund_amount <= 0` or
wallet `total_billed <= 0`.

### Prod — 2 invoices

| Invoice | Txn | Total | Paid | Refund | kWh | Status |
|---|---|---|---|---|---|---|
| VL/F1/QR/202627/00007 | 831 | ₹5.00 | 250 | 250 | **26.462** | REFUNDED / COMPLETED |
| VL/F3/QR/202627/00061 | 1027 | ₹1.00 | 50 | 50 | 0.188 | REFUNDED / COMPLETED |

### Staging — 11 invoices

- **3 QR** fully-refunded: `VL/F5/QR/202627/00367`, `00369`, `00370` (~0.2 kWh,
  ₹0.10 each) — same class as invoice 61.
- **8 WAL** zero-value / `BILLING_FAILED` (₹0.00; wallet sessions, `total_billed`
  NULL): txns 66, 81, 86, 129, 130, 132, 139, 153.

### Two structural classes

1. **QR fully-refunded** — non-zero total = synthetic gateway line only; asserts a
   phantom taxable supply and consumed a sequential invoice number.
2. **WAL zero-value / BILLING_FAILED** — ₹0.00 total; wallet sessions whose
   billing never completed. Still consumed an invoice number.

---

## 5. Decision — leave already-issued invoices as-is

**Decision (2026-07-09): no remediation of the existing orphaned invoices.** They
are left in place and annotated here; no credit notes, no voids.

**Rationale:** small blast radius (2 prod, 11 staging), low per-invoice value
(₹1–5 or ₹0), and the forward fix (issue 01) stops new ones. Voiding/credit-noting
consumed GST numbers carries its own GSTR-1 handling cost that isn't justified at
this volume.

**Consequence to accept:** a handful of historical invoices assert a small taxable
gateway supply against fully-refunded payments. If a future GST review requires
clean-up, re-open issue 02 and issue credit notes.

---

## 6. Flag beyond this work — prod txn 831 (separate revenue-loss bug)

`VL/F1/QR/202627/00007` delivered **26.462 kWh** on a **COMPLETED** session yet was
**fully refunded ₹250** with `energy_charge` NULL. This is NOT the fault-refund
band (that requires FAILED + <0.5 kWh) — it's real energy given away for free. It
warrants its own RCA: why a completed multi-kWh session fully refunded without a
billing breakdown. Not addressed here.

---

## 7. Status of the tracked issues

| # | Title | Status |
|---|---|---|
| 01 | Net-retained invoice-issuance guard | done (uncommitted) |
| 02 | Reconcile orphaned invoices | resolved — leave as-is (this record) |
| 03 | ADR + context-doc update | ready-for-agent (pending) |

Separate/uncommitted: `:.1f`→`:.3f` kWh-column display fix (invoice 60).
Suggested new issue: RCA for prod txn 831 (26 kWh fully-refunded).
