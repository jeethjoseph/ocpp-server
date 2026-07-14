# Admin tariff form → GST-included input, base + GST preview

Status: ready-for-agent

## What to build

Update the admin chargers create/edit tariff UI to the new model (ADR 0026). The operator input is the GST-inclusive, gateway-exclusive **Tariff** (`rate_gst_included`); the live `TariffBreakdownPreview` shows two rows — the back-calculated base rate and the GST — with the gateway noted as a separate, actual charge that varies per payment (no gateway baked into the tariff). Remove the `back_derive_rate_per_kwh` mirror and the `PLATFORM_FEE_PERCENT` constant from the frontend where they only fed the old gateway-in-tariff preview; update `breakdownAllInTariff` (or its replacement) accordingly. Update the Vitest specs to cover the new two-row breakdown, and run the full production build (scoped lint/tsc are not sufficient per repo policy).

## Acceptance criteria

- [ ] Admin tariff input is labelled/handled as `rate_gst_included` (GST-incl, gateway-excl); saves round-trip via the slice-01 API
- [ ] `TariffBreakdownPreview` shows base rate + GST; gateway shown as a separate note (actual, varies), not folded into the tariff
- [ ] Frontend `back_derive_rate_per_kwh` mirror + obsolete `PLATFORM_FEE_PERCENT` usage removed
- [ ] `frontend/__tests__/` specs updated for the new breakdown; `npm run test:run` green
- [ ] `cd frontend && npm run build` passes

## Blocked by

- 01-rename-tariff-columns-back-calc-base-rate.md
