# Tariffs are stored and displayed as "all-inclusive"; `rate_per_kwh` is back-derived

Customer-facing tariffs are now expressed as a single **all-in** number — the per-kWh price a customer effectively pays at full budget consumption, inclusive of both GST and the synthetic 2% gateway fee. A new column `Tariff.tariff_per_kwh_all_in` is the operator-typed source of truth; the existing `Tariff.rate_per_kwh` is back-derived on save as `all_in × 0.98 / 1.18` and used only for internal line-item math. The previous `tariff_per_kwh_incl_tax` API field is **replaced** (not aliased) by `tariff_per_kwh_all_in` — keeping both around would invite "wrong number in new component" bugs given the term overlap. The customer-facing UI label changes from `(incl. GST)` to `(all-inclusive)`.

## Migration

On deploy day, an Aerich migration:

1. Adds `tariff_per_kwh_all_in` (initially nullable).
2. Backfills `tariff_per_kwh_all_in = rate_per_kwh × (1 + gst_percent/100)` so today's customer-facing displayed number is preserved.
3. Shrinks `rate_per_kwh *= 0.98` so the back-derivation identity (`all_in × 0.98 / 1.18 = rate_per_kwh`) holds going forward.
4. Tightens `tariff_per_kwh_all_in` to NOT NULL.

This means franchisees absorb a 2% margin reduction on legacy tariffs until they explicitly re-enter them in the admin UI. The hit lands on VoltLync's books in the form of a lower `rate_per_kwh` (and thus lower `energy_taxable_value` on every invoice for legacy tariffs). The operations team coordinates re-entry manually — at the time of this ADR there are only two live chargers, so a dedicated "legacy tariffs" tracking column and admin banner were considered and rejected as bloat. If the fleet grows materially before re-entry, the banner can be added back (an indexed `last_operator_save_at` timestamp on `Tariff` would be enough).

Per the cutover plan, the migration runs in a coordinated maintenance window with all live sessions stopped — no Redis stale-cache concerns.

## Considered alternatives

- **Preserve `rate_per_kwh` as-is; inflate the displayed all-in by 2% on deploy day.** Rejected: silently raises customer-facing prices overnight without operator authorisation.
- **NULL `tariff_per_kwh_all_in` until operators re-enter; hard-block chargers in the meantime.** Rejected: operationally painful — every charger goes offline at deploy until manually touched.
- **Repurpose `rate_per_kwh` to mean all-in; drop the back-derivation.** Rejected: huge blast radius across billing, invoicing, settlement, simulators, and tests, all of which currently treat `rate_per_kwh` as excl-everything.
- **Track `operator_set_all_in_at` + ship a legacy-tariff banner endpoint.** Rejected at the size we're at — two live chargers is well within manual coordination range. Reconsider when the operator-set audit trail or self-serve "what changed" tooling becomes useful in its own right.

## Consequences

- The displayed all-in rate is **exact only at full budget consumption**. Partial consumption inflates the customer's effective per-kWh slightly (the synthetic fee is a fixed rupee amount on `amount_paid`, not per-kWh). This is intentional and not disclosed in-line — see grilling notes 2026-05-18.
- Going forward, `rate_per_kwh` is never customer-facing and never displayed; treat it as a private implementation detail of the billing math.
- If `RAZORPAY_PLATFORM_FEE_PERCENT` is ever changed, existing tariff rows do NOT automatically re-derive — they keep the stored `rate_per_kwh` and `tariff_per_kwh_all_in` as-is. Operators must re-save to pick up the new policy.
