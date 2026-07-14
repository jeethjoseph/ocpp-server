# Plan — Tariff excludes gateway; gateway = actual webhook fee (ADR 0026)

Status: **finalized, awaiting approval to implement**. Supersedes the earlier "bill-off-all-in / retire rate_per_kwh" draft. Design locked via grill-with-docs 2026-07-13. See `docs/adr/0026`, `CONTEXT.md`.

## The model (locked)

- **Tariff** = operator-typed, GST-inclusive, **gateway-exclusive** energy price → `Tariff.rate_gst_included` (renamed from `tariff_per_kwh_all_in`, value unchanged).
- **Base rate** = `rate_gst_included / (1 + gst%/100)` → `Tariff.rate_per_kwh` (RETAINED column, back-calculated).
- **Energy** billed directly: `energy_cost = kWh × base_rate`; `gst = energy_cost × gst%`. Never a residual — cannot distort.
- **Gateway fee** = ACTUAL Razorpay webhook fee on `amount_paid` (already captured on QRPayment row), billed as a **separate customer line**. Synthetic 2% retired.
- **Refund (QR)** = `amount_paid − energy_incl_gst − actual_gateway`.
- **Pass-through**: gateway added to customer bill, subtracted in refund AND settlement `pg_fee` → cancels out of franchisee payout (pool = `kWh × base_rate`).
- **Budget cap** = `(amount_paid − actual_gateway) / (rate_per_kwh × (1 + gst%/100))`, reserved at StartTransaction.
- **Wallet** unchanged: base + GST, no gateway line, `pg_fee = 0`.
- **Historical**: fix-forward only (₹346 de-minimis, documented in ADR 0026).

## Migration (Aerich — one schema change + back-calc)

Model field renames, then `aerich migrate`; add the back-calc + snapshot rename in `upgrade()`:
```sql
-- Tariff: rename column (value unchanged), recompute base rate
ALTER TABLE tariff RENAME COLUMN tariff_per_kwh_all_in TO rate_gst_included;
UPDATE tariff SET rate_per_kwh = ROUND(rate_gst_included / (1 + gst_percent/100), 4);
-- GSTInvoice: rename snapshot column (historical values unchanged)
ALTER TABLE gst_invoice RENAME COLUMN tariff_per_kwh_all_in TO rate_gst_included;
```
`downgrade()` reverses the renames + restores `rate_per_kwh = rate_gst_included × 0.98/1.18`.
Follow the Aerich workflow: `aerich upgrade` first (sync local), rename model fields, `aerich migrate`, accept the rename prompt if offered; splice the UPDATE into the generated file. No snapshot poisoning (data UPDATE + rename, not schema removal by hand).

## File-by-file

### Backend
- **`models.py`** — `Tariff.tariff_per_kwh_all_in → rate_gst_included`; `GSTInvoice.tariff_per_kwh_all_in → rate_gst_included`; fix both stale column comments (`rate_per_kwh` is now `= rate_gst_included/(1+gst)`, no gateway).
- **`services/tariff_utils.py`** — remove `synthetic_platform_fee`, `synthetic_fee_split`, `back_derive_rate_per_kwh`; add `back_calc_base_rate(rate_gst_included, gst_pct) = rate_gst_included/(1+gst/100)`; `compute_station_tariff_range` returns the `rate_gst_included` range (+ derive an excl value for the retained public `price_per_kwh` field — see P1).
- **`services/qr_payment_service.py`** — `process_qr_session_billing` / `_compute_qr_energy_cost`: energy = `kWh × base_rate`; gateway = actual fee (via `_ensure_actual_fee_captured`, now operative not ops-only); `refund = amount_paid − energy_incl_gst − actual_gateway` (floored at 0). `link_transaction_to_qr_payment` + `_load_or_rebuild_qr_session`: cache `base_rate`/`gst`/`max_kwh` using actual gateway. `compute_budget_snapshot`/`check_budget_and_auto_stop`: reserve actual gateway. Non-billable bands (zero / FAILED<0.5) unchanged. Remove `_ensure_actual_fee_captured`'s 2%-estimate fallback path or keep as last-resort only (decide at impl — actual is now customer-facing).
- **`services/wallet_service.py`** — `calculate_billing_amount` unchanged in shape; source rate from `base_rate` (already does via `rate_per_kwh`). Drop synthetic references. No gateway.
- **`services/wallet_session_service.py`** — budget cache uses `base_rate` (already reads `rate_per_kwh`); confirm no synthetic.
- **`services/invoice_service.py`** — gateway line = stored actual (`qr_payment.platform_fee`/`razorpay_commission`/`razorpay_gst`) instead of `synthetic_fee_split(amount_paid)`; energy from `txn.energy_charge`/`gst_amount` (unchanged); `billable_kwh` uses `txn.energy_consumed_kwh` directly (drop `energy_taxable/rate_per_kwh` division — but rate_per_kwh retained so either works); snapshot writes `rate_gst_included`; wallet gateway stays 0. ADR 0023 net-retained guard unchanged (still valid, now never triggered by a clamp since no clamp).
- **`services/franchisee_settlement_service.py`** — `pg_fee = actual gateway` (`qr_payment.razorpay_commission + razorpay_gst`) instead of `synthetic_platform_fee`; wallet `pg_fee = 0` unchanged. `tariff_rate_per_kwh` snapshot already per-bill.
- **`services/tariff_drift_check.py`** — **delete module** + its `main.py` startup call + `Custom/Tariff/IdentityDrift` metric (no synthetic identity to police).
- **`core/config.py`** — remove `RAZORPAY_PLATFORM_FEE_PERCENT` + `validate_platform_fee_percent` startup check.
- **`routers/chargers.py`** — input schema takes `rate_gst_included` (GST-incl, gateway-excl; validation range check); store it + back-calc `rate_per_kwh`; response echoes `rate_gst_included` (+ keep `tariff_per_kwh`/rate for internal if consumed). Remove `back_derive` import.
- **`routers/users.py`** — charger detail returns `rate_gst_included` (drop old all-in name).
- **`routers/public_stations.py`** — `min/max` range on `rate_gst_included`; P1: keep `price_per_kwh` populated (derive `= rate_gst_included/1.18` nominal) so the public API + frontend don't break.
- **`routers/public_qr_active_sessions.py`** — live cost via `base_rate`; reserve actual gateway (remove `synthetic_platform_fee`).
- **`routers/public_qr_transactions.py`** — customer history fallback (`:63`): gateway split from stored actual, not `synthetic_fee_split`.
- **`scripts/seed_data.py`, `scripts/seed_docker.py`** — write `rate_gst_included` + back-calc `rate_per_kwh`.

### Frontend (then `cd frontend && npm run build`)
- **`lib/utils.ts`** — remove `back_derive_rate_per_kwh` mirror; `breakdownAllInTariff` → two rows (base rate, GST), gateway shown as a separate note (actual, varies).
- **`lib/constants.ts`** — remove `PLATFORM_FEE_PERCENT` (or keep only if still referenced for display copy).
- **`components/TariffBreakdownPreview.tsx`** — relabel to `rate_gst_included` input → base rate + GST; drop gateway-in-tariff line.
- **`lib/api-services.ts`** + any component reading `price_per_kwh` / the old all-in field name — rename to `rate_gst_included`; `price_per_kwh` retained (P1).
- **`__tests__/`** — update `breakdownAllInTariff` + `TariffBreakdownPreview` specs; remove synthetic-fee expectations.

### Docs
- `docs/adr/0026-*` (written). Mark ADR 0001 + 0003 gateway portions superseded (status line pointing to 0026). Update `docs/known-issues.md#1` (narrowed, not fixed). Update `docs/v1/llm-context-document.md` + `docs/v1/comprehensive-architecture-documentation.md`.

## Test blast radius (backend per-file via `docker exec ocpp-backend pytest`)
- **Fixtures**: `conftest.py:219` + ~16 test files set `rate_per_kwh=` / `tariff_per_kwh_all_in=` — update to `rate_gst_included=` (rate_per_kwh still settable/derivable). Fixture rename is mechanical but wide.
- **Delete** `test_tariff_drift_check.py`; **rewrite** `test_tariff_all_in_migration.py` (back_derive gone → back_calc) and the synthetic-fee unit tests in `test_qr_payment_service.py:1172-1194`.
- **New/updated**: QR energy = kWh×base_rate at partial & full; refund = paid − energy_incl_gst − actual_gateway; gateway line = actual (webhook) on invoice; budget cap reserves actual gateway; settlement pg_fee = actual, franchisee pool = kWh×base_rate independent of gateway; wallet base+GST no gateway; invoice reconciliation `total_amount + refund == amount_paid` with actual gateway; historical invoices re-render from stored fields unchanged.

## Verified pitfalls (from architecture review) — status
- **P1 public `price_per_kwh`**: retained, derived nominal from `rate_gst_included` — no frontend break. ✅ handled in plan.
- **P2 clamp / phantom invoice (ADR 0023)**: ELIMINATED — energy is `kWh×base_rate`, never a residual, so no clamp exists. ✅
- **P3 stackable budget (ADR 0021)**: unimplemented; single-payment assumption documented in ADR 0026. ✅
- **Console revenue**: `build_revenue` reads stored `txn.energy_charge`/`total_billed` (energy-only) — keep writing those energy-only; gateway shown via `razorpay_fee` (actual). ✅
- **Historical invoices**: compute-path change only, never a backfill. ✅

## Rollout
- Two-phase column rename NOT required (single-box compose stops old container before new serves); but run migration in a low-traffic window. In-flight QR sessions: readers rebuild-from-DB on cache miss and final billing reads tariff fresh → mid-charge sessions bill correctly.
- Ops note: existing tariffs' effective customer total ticks up ~2% (gateway now on top); admin-adjustable; ~2 live chargers.

## Suggested sequence
1. Migration (rename + back-calc) + models.py + fixtures green
2. tariff_utils (back_calc, remove synthetic) + config cleanup
3. QR billing + budget + active-sessions + qr history
4. Wallet (minimal) + invoice + settlement
5. Delete drift-check + tests
6. Frontend + `npm run build`
7. Docs (ADR status lines, known-issues, v1 docs) + full per-file pytest
