# Retire the synthetic platform-fee scaffolding

Status: ready-for-agent

## What to build

Remove the synthetic 2% gateway-fee machinery now that the gateway is the actual Razorpay webhook fee (ADR 0026). Delete `synthetic_platform_fee` and `synthetic_fee_split` from `tariff_utils`, add a small `back_calc_base_rate(rate_gst_included, gst_pct)` helper (`= rate_gst_included / (1 + gst_pct/100)`), delete the `tariff_drift_check` module together with its `main.py` startup call and the `Custom/Tariff/IdentityDrift` metric, and remove `RAZORPAY_PLATFORM_FEE_PERCENT` plus its `validate_platform_fee_percent` startup validation from `core/config.py`. There is no synthetic identity left to police, so the drift checker and the fee-percent bands are dead.

This is a pure removal/refactor slice — no behavior change on its own, but it clears the scaffolding so the billing slices read cleanly. Callers of the deleted synthetic helpers are migrated in slices 03/04/05; this slice only removes the definitions and the drift/config surface, plus any now-dead imports it can safely drop.

## Acceptance criteria

- [ ] `synthetic_platform_fee` / `synthetic_fee_split` removed; `back_calc_base_rate` added and unit-tested
- [ ] `services/tariff_drift_check.py` deleted; its `main.py` startup invocation and `Custom/Tariff/IdentityDrift` metric removed
- [ ] `RAZORPAY_PLATFORM_FEE_PERCENT` + `validate_platform_fee_percent` removed from `core/config.py` and any env/compose references
- [ ] `test_tariff_drift_check.py` deleted; synthetic-fee unit tests in `test_qr_payment_service.py` removed/rewritten
- [ ] App boots clean; no dangling imports of removed symbols; affected per-file pytest green

## Blocked by

- 01-rename-tariff-columns-back-calc-base-rate.md
