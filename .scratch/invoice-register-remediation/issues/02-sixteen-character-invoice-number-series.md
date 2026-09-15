# New 16-character GST Invoice number series

Status: done

## What to build

Replace the GST Invoice numbering format with one that satisfies **Rule 46(b) CGST**, which caps the serial number at **sixteen characters**. Every invoice issued to date is 18–22 characters and therefore breaches it:

| Length | Count | Example |
|---|---|---|
| 18 | 54 | `VL/QR/202627/00001` |
| 19 | 3 | `VL/WAL/202627/00001` |
| 21 | 1,139 | `VL/F1/QR/202627/00001` |
| 22 | 5 | `VL/F5/WAL/202627/00001` |

New format, exactly 16 characters:

```
F0001/Q/26/00001
│     │ │  └── sequence, 5 digits — 99,999 per franchisee per financial year
│     │ └───── financial-year start year (2026-27 → 26)
│     └─────── series: Q = QR/UPI, W = Wallet
└───────────── Franchisee.invoice_code from issue 01; F0000 = VoltLync-owned
```

The `VL/` prefix is dropped — Rule 46 requires the supplier's name, address and GSTIN as separate invoice fields, so the number carries no branding obligation, and the four characters are needed elsewhere. The wallet series shortens from `WAL` to `W`; a 5-digit sequence is required because a single busy franchisee can exceed 9,999 sessions a year (Arunraj R is at ~3,500 annualised on one site).

**Existing invoice numbers are not touched.** Rule 46(b) expressly permits "one or multiple series", so the old format becomes a closed series and the new one begins at cutover, each franchisee restarting at `00001`. Renumbering an issued invoice would put a customer's document out of step with our books — the exact defect being remediated. **This explicitly includes the two known duplicates**: both copies of `VL/F2/QR/202627/00001` were rendered to PDF and are in customers' hands, so no clean renumbering exists. They are recorded in the file note under issue 03 and left in place.

Cutover is the first invoice issued after deploy — no dated flag, no backfill. `GSTInvoiceCounter` keys on `(franchisee, series, financial_year)` and simply begins a fresh row for the new series value.

## Acceptance criteria

- [ ] `get_next_invoice_number` emits `{invoice_code}/{Q|W}/{YY}/{SEQ:05d}`, exactly 16 characters, using `Franchisee.invoice_code`
- [ ] VoltLync-owned sessions (`franchisee_id IS NULL`) emit under `F0000`
- [ ] Financial year still derived in IST per ADR 0012 — an invoice raised just after IST-midnight on 1 April lands in the new FY
- [ ] A test asserts generated numbers are `<= 16` characters for every series and for a 5-digit sequence
- [ ] A test asserts the atomic `SELECT FOR UPDATE` counter still holds under concurrent issuance and produces no gaps or repeats
- [ ] Existing invoice numbers are unchanged — a test asserts no historical row is rewritten
- [ ] The two duplicate `VL/F2/...` numbers remain untouched
- [ ] Admin invoice list, CSV export and invoice PDF render the new format without truncation or layout break
- [ ] Affected per-file pytest green (`docker exec ocpp-backend pytest`)

## Blocked by

- `.scratch/invoice-register-remediation/issues/01-franchisee-invoice-code-partitioned-allocation.md`
