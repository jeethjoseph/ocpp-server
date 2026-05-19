# Frontend: all-in tariff field swap, "(all-inclusive)" label, admin form preview

Status: ready-for-agent

## What to build

Customer-facing and admin UIs surface the new **All-in tariff** in place of the old `tariff_per_kwh_incl_tax`. The customer-facing parenthetical changes from `(incl. GST)` to `(all-inclusive)`. The admin tariff form shows a live preview of the back-calculated breakdown as the operator types.

### Field rename across frontend

Replace every reader of `tariff_per_kwh_incl_tax` with `tariff_per_kwh_all_in` across:

- Public stations page (per-charger chip + station price range).
- My-charges page (station price range in transaction details).
- Admin chargers list and detail.
- Admin chargers create/edit form (field name and label).
- Admin GST filings page (invoice tariff column — note the API still serves the per-invoice `tariff_rate_incl_tax` from the `GSTInvoice` row unchanged; only the `Tariff` model's field changes).

### Label change

Customer-facing per-kWh chips and price ranges read `(all-inclusive)` instead of `(incl. GST)`. The admin form input label also reads `Tariff (₹/kWh, all-inclusive)` so the operator types the same number the customer sees.

### Admin form live preview panel

Below the all-in tariff input on the admin chargers create/edit form, render a small read-only panel that updates as the operator types:

```
→ Base rate (rate_per_kwh):  ₹20.7627/kWh
→ Gateway fee (2%):          ₹0.5000/kWh
→ GST (18%):                 ₹3.7373/kWh
```

Computed client-side using the same formula as the backend (gateway fee deducted first, then GST backed out). Refresh on every keystroke.

### Post-migration re-entry

The originally-planned legacy-tariff banner was dropped — at two live chargers, ops handles re-entry manually via the new admin form. No banner UI required. See ADR 0003.

### Build verification

Per CLAUDE.md: after frontend edits, run `cd frontend && npm run build` (the full production build, not just `tsc --noEmit` or `next lint`).

See [ADR 0003](../../../docs/adr/0003-all-inclusive-tariff-with-operator-absorption.md) and [CONTEXT.md](../../../CONTEXT.md).

## Acceptance criteria

- [ ] No occurrence of `tariff_per_kwh_incl_tax`, `min_price_per_kwh_incl_tax`, or `max_price_per_kwh_incl_tax` remains in the frontend codebase (grep returns empty).
- [ ] Public stations page renders `₹X/kWh (all-inclusive)` per charger; price-range displays use the new fields.
- [ ] Admin chargers create form: typing `25` into the tariff input updates the preview panel to show `rate_per_kwh ≈ ₹20.7627`, `gateway ≈ ₹0.50`, `GST ≈ ₹3.7373`.
- [ ] Admin chargers edit form prefills the all-in value from the API and shows the same live preview on edit.
- [ ] `cd frontend && npm run build` completes successfully (no lint or type errors).
- [ ] Visual QA in a browser: confirm the customer-facing pricing on the stations page renders correctly with the new label and field; confirm the admin form preview is legible.
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated per CLAUDE.md.

## Blocked by

Issue 04 (the API must expose `tariff_per_kwh_all_in`).
