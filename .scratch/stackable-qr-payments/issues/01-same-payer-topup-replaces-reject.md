# 01 — Same-payer top-up replaces reject-when-busy (summed budget)

Status: ready-for-agent

## What to build

Turn the "charger busy ⇒ reject + full-refund" path into a same-payer **QR budget top-up**, per ADR 0021. This is the core vertical slice: after it, a customer can pay again mid-session and keep charging past their first payment's budget, with no StopTransaction at the seam.

When a QR payment webhook resolves to a charger that already has a **CHARGING** transaction:

- If the incoming payer **matches** the active session's payer — `customer_vpa`, falling back to `customer_contact`/phone — treat it as a **Stacked QR payment**: link the new `QRPayment` to the active `Transaction` (status `CHARGING`), and set the Redis `qr_session:{txn}` `budget_limit_paise` to the **running sum** of `(amount_paid − synthetic_platform_fee)` across all linked CHARGING payments.
- If the payer **does not match** — a different person scanning a busy charger — keep today's behavior **exactly**: reject + full-refund.

There is exactly one `Transaction` (the OCPP session); stacking only extends its budget. `QRPayment → Transaction` becomes 1:N (the FK already permits it — no migration).

## Acceptance criteria

- [ ] Same-payer payment on a CHARGING charger links to the active transaction and raises the Redis budget to the summed net amount
- [ ] Charging continues past the first payment's budget with no StopTransaction at the seam
- [ ] Different-payer payment on a busy charger still rejects + full-refunds (unchanged)
- [ ] Payer matching uses `customer_vpa` with `customer_contact`/phone fallback
- [ ] Budget sum uses the synthetic platform fee per ADR 0001, per payment
- [ ] No new `Transaction` row is created for a top-up
- [ ] Per-file pytest: same-payer top-up extends budget; stranger rejected+refunded; multi-stack sum correct

## Blocked by

- None - can start immediately
