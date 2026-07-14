# QR billing → energy-from-base-rate + actual gateway, budget reserves actual fee

Status: ready-for-agent

## What to build

Rewire the QR charging path so energy is billed directly and the gateway is the actual Razorpay fee (ADR 0026). At StopTransaction billing, compute `energy_cost = energy_kwh × base_rate`, `gst = energy_cost × gst%`, take the gateway from the actual webhook fee already captured on the QRPayment row (`platform_fee`/`razorpay_commission`/`razorpay_gst`), and set `refund = amount_paid − energy_incl_gst − actual_gateway` (floored at 0). The budget cap becomes `max_kwh = (amount_paid − actual_gateway) / (rate_per_kwh × (1 + gst%/100))`, reserved at StartTransaction and cached; the auto-stop, cache-rebuild, and live-KPI reads (`public_qr_active_sessions`) and the customer history fallback (`public_qr_transactions`) all move off the synthetic fee onto the actual. The non-billable bands (zero-energy, FAILED < 0.5 kWh) are unchanged.

The energy line is now computed directly, never as a residual after subtracting a gateway — this structurally eliminates the ADR 0023 phantom-invoice / clamp class. Because the gateway is reserved out of the budget, a session's final refund can never go negative and force VoltLync to eat the fee. Single-payment assumption holds (reject-on-busy; ADR 0021 stacking is unimplemented).

`_ensure_actual_fee_captured` is promoted from ops-only to the operative fee source; keep its API/webhook priority, and decide at implementation whether to keep the 2%-estimate as a last-resort fallback (now that the value is customer-facing) or drop it — record the choice in the PR.

## Acceptance criteria

- [ ] QR StopTransaction bills `energy_cost = energy_kwh × base_rate`; effective energy ₹/kWh equals the tariff at both partial and full consumption
- [ ] Gateway on the session is the actual webhook fee; `refund = amount_paid − energy_incl_gst − actual_gateway`, floored at 0
- [ ] Budget cap reserves the actual gateway (`max_kwh` formula above); auto-stop, link, and cache-rebuild use it; zero-MDR (fee ₹0) lets the full prepay go to energy
- [ ] `public_qr_active_sessions` live cost + `public_qr_transactions` history fallback compute off actual fee, not synthetic
- [ ] Non-billable bands (zero-energy, FAILED sub-0.5) unchanged
- [ ] `transaction.energy_charge`/`gst_amount`/`total_billed` stay energy-only (gateway not folded in) so the admin console revenue tally still reconciles
- [ ] Per-file pytest green incl. new cases: partial/full effective rate, refund with actual gateway, over-consumption, budget parity

## Blocked by

- 01-rename-tariff-columns-back-calc-base-rate.md
- 02-retire-synthetic-fee-scaffolding.md
