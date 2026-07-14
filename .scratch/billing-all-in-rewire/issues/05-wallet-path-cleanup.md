# Wallet path cleanup — base + GST, no gateway line

Status: ready-for-agent

## What to build

Confirm and clean up the wallet charging path under the new model (ADR 0026). Wallet sessions bill `total_billed = energy_kwh × base_rate + GST` with **no gateway line** (the gateway fee is a top-up-time cost, absorbed at top-up, not per session) and `pg_fee = 0` in settlement — this is already the system's behavior, so the slice is mainly removing any lingering synthetic-fee references in `wallet_service` / `wallet_session_service` and ensuring the base rate is sourced correctly from `rate_per_kwh` after the rename. No new gateway line is introduced on `WAL` invoices.

## Acceptance criteria

- [ ] Wallet session bills energy at `base_rate` (+ GST); `total_billed = energy_charge + gst_amount`, no gateway component
- [ ] `WAL` GST Invoice has gateway line = 0; settlement `pg_fee = 0` for wallet
- [ ] No `synthetic_platform_fee`/`RAZORPAY_PLATFORM_FEE_PERCENT` references remain in the wallet services
- [ ] Wallet budget cap (`wallet_session_service`) uses `base_rate`, consistent with QR
- [ ] Per-file pytest green (wallet billing, GST, concurrent-writes, end-to-end)

## Blocked by

- 01-rename-tariff-columns-back-calc-base-rate.md
- 02-retire-synthetic-fee-scaffolding.md
