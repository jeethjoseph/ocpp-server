# 02 — Rebuild-must-sum durability fix

Status: ready-for-agent

## What to build

Fix the budget-rebuild path so a stacked QR Session survives a Redis cache miss without cutting off a paid-up customer, per ADR 0021 (the durability trap).

`_load_or_rebuild_qr_session` currently rebuilds the budget from a single `.first()` CHARGING payment. For a stacked session that collapses the budget to one payment's worth on a Redis blip, so the next MeterValues frame sees `cost > budget` and fires a **spurious RemoteStop** on a customer who has paid to charge longer.

The rebuild must **sum all CHARGING `QRPayment`s** linked to the transaction (same `(amount_paid − synthetic_platform_fee)` summation as the top-up write). The DB is the durable source of truth for the summed budget.

## Acceptance criteria

- [ ] `_load_or_rebuild_qr_session` sums all CHARGING payments for the transaction, not a single row
- [ ] Rebuilt `budget_limit_paise` equals the pre-eviction summed budget
- [ ] Evicting the `qr_session:{txn}` cache mid-stacked-session does not trigger a RemoteStop while `cost < summed budget`
- [ ] Single-payment (non-stacked) sessions rebuild identically to before (no regression)
- [ ] Per-file pytest simulating cache miss on a 2+ payment session asserts no spurious stop

## Blocked by

- 01 — Same-payer top-up replaces reject-when-busy (summed budget)
