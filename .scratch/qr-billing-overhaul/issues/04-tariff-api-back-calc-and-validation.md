# Tariff API back-calc, field rename, and validation

Status: ready-for-agent

## What to build

Wire the new **All-in tariff** column into the API surface. The operator types one number; the backend derives `rate_per_kwh` server-side and persists both. The customer-facing `tariff_per_kwh_incl_tax` response field is replaced (not aliased) with `tariff_per_kwh_all_in`.

### Tariff write path

Admin tariff create and update endpoints accept `tariff_per_kwh_all_in` in the request body. The backend computes:

```
rate_per_kwh = tariff_per_kwh_all_in × (1 - RAZORPAY_PLATFORM_FEE_PERCENT/100) / (1 + gst_percent/100)
```

and persists both columns. The previous form of accepting `tariff_per_kwh_incl_tax` is removed.

Validation: `1.0 ≤ tariff_per_kwh_all_in ≤ 100.0` (sanity floor and ceiling, fat-finger guard).

### Read path

Replace `tariff_per_kwh_incl_tax` with `tariff_per_kwh_all_in` in every response schema that exposes per-charger or per-station tariff information. Update the station price-range helper to compute min/max over `tariff_per_kwh_all_in` instead of the derived incl-tax figure. The previous `min_price_per_kwh_incl_tax` / `max_price_per_kwh_incl_tax` station fields are renamed to `min_price_per_kwh_all_in` / `max_price_per_kwh_all_in`.

The **GST Invoice** generator is unchanged in value: the per-kWh rate it displays remains the GST-only `(energy_taxable + energy_tax) / billable_kwh` figure, because the gateway fee is itemised separately on the invoice. Only the response-schema-level field name changes propagate; the invoice PDF math is untouched.

(The originally-planned `GET /api/admin/tariffs/legacy` endpoint + `operator_set_all_in_at` tracking column were dropped — at two live chargers, ops handles post-migration re-entry manually. See ADR 0003.)

See [ADR 0003](../../../docs/adr/0003-all-inclusive-tariff-with-operator-absorption.md) and [CONTEXT.md](../../../CONTEXT.md).

## Acceptance criteria

- [ ] `POST/PATCH` to the admin tariff endpoint with `{"tariff_per_kwh_all_in": 30.00}` and `gst_percent=18` results in `rate_per_kwh ≈ 24.9153`.
- [ ] Submitting `tariff_per_kwh_all_in` outside `[1.0, 100.0]` returns a 422 validation error.
- [ ] The previous `tariff_per_kwh_incl_tax` field is no longer accepted on writes or returned on reads — requests using it return a validation error or a 422.
- [ ] `tariff_per_kwh_all_in` appears on every response that previously exposed `tariff_per_kwh_incl_tax`: charger detail, charger list, public station list, station detail, my-charges.
- [ ] Station price range responses use `min_price_per_kwh_all_in` and `max_price_per_kwh_all_in`, computed over all-in values.
- [ ] Invoice generation and PDF output are unchanged in value — verified by snapshot test on an existing test fixture.
- [ ] Unit tests cover the back-calc formula across edge cases (different GST rates, different fee percentages via env var override).
- [ ] Integration test exercises the full create → read flow.
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated per CLAUDE.md.

## Blocked by

Issue 03 (the schema migration must land first so the columns exist).
