# Doc + label hygiene + GST test coverage + seed_data correctness

Status: ready-for-agent

## What to build

Four small unrelated polish items bundled into one PR because each is trivial on its own:

- **M4 — stale `.env.example` comments.** All three `.env*.example` files describe `RAZORPAY_PLATFORM_FEE_PERCENT` as "Fallback fee estimate (%) when actual Razorpay fee unavailable." Post-ADR-0001 the variable is the **authoritative** synthetic rate that drives every customer-facing calculation. The old comment will confuse future engineers reading the example.
- **M5 — GST rate coverage gap.** The back-derivation tests parameterize over 18 / 5 / 28 / 0 percent. Real Indian GST has a 12% bracket too (for some service categories); a 12% case in the parameterized fixtures gives confidence that the formula handles all real-world brackets.
- **L1 — hardcoded `(2%)` / `(18%)` labels in `TariffBreakdownPreview`.** The React component (`frontend/app/admin/chargers/page.tsx`) hardcodes the percentage labels in the displayed strings. If `RAZORPAY_PLATFORM_FEE_PERCENT` ever changes, the labels lie. The math itself uses defaults that can be overridden via props, but the labels are static.
- **L3 — `seed_data.py` violates the back-calc identity.** Post-edit, the script computes `all_in = rate × 1.18` for seeded tariffs — that's the migration-equivalent formula, not the runtime back-derivation. So `back_derive_rate_per_kwh(all_in) != rate` for any seeded row. Dev fixtures only, but a future engineer running the seed and then using the admin UI to view the seeded charger will see numbers that don't satisfy the documented invariant.

### Plan

- Update the three `.env.example` comments (one line each in `backend/.env.example`, `.env.staging.example`, `.env.prod.example`) to: `Authoritative synthetic platform-fee rate (%) — drives budget cap, refunds, invoice gateway lines. See ADR 0001.`
- Add `(Decimal("33.00"), Decimal("12.00"))` to the `BACKFILL_FIXTURES` list in `test_tariff_all_in_migration.py`.
- Refactor `TariffBreakdownPreview` to accept `feePercent` and `gstPercent` as required props (no defaults). Caller (the admin form) passes them from a shared frontend constant (e.g., `frontend/lib/constants.ts` exporting `PLATFORM_FEE_PERCENT = 2` and `DEFAULT_GST_PERCENT = 18`). The label rows become `\`→ Gateway fee (${feePercent}%):\``.
- Rewrite `seed_data.py` to pick the all-in figure first, then back-derive `rate_per_kwh` via the same formula the admin form uses. This keeps seeded data structurally identical to production-admin-entered data and satisfies the runtime identity check from Slice 2.

## Acceptance criteria

- [ ] All three `.env*.example` comments updated; describe authoritative-synthetic semantic.
- [ ] `BACKFILL_FIXTURES` covers 0 / 5 / 12 / 18 / 28 percent GST.
- [ ] `TariffBreakdownPreview` no longer hardcodes `(2%)` or `(18%)` in the rendered string; props are required.
- [ ] `frontend/lib/constants.ts` (or equivalent) exports the percent constants used by the preview.
- [ ] `python scripts/seed_data.py` against a fresh DB produces tariffs satisfying `abs(back_derive_rate_per_kwh(t.tariff_per_kwh_all_in, t.gst_percent, 2.0) - t.rate_per_kwh) < 0.0001` for every row.
- [ ] `cd frontend && npm run build` clean.
- [ ] Backend test suite green.

## Blocked by

Slice 1 (config & helper relocation) — the seed-data rewrite reads the synthetic-fee constant cleanly only after Slice 1 has moved it to a shared location, and the frontend constants file is the symmetric move.
