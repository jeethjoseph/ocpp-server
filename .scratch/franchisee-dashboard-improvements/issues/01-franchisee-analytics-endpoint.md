# 01 — Franchisee analytics endpoint (payout/energy/sessions buckets + per-charger)

Status: ready-for-agent

## What to build

A franchisee-scoped analytics endpoint that feeds the dashboard graphs. Returns time-bucketed series plus a per-charger breakdown, all scoped to the authenticated franchisee's chargers.

- Buckets over a selectable range of: **`franchisee_payout`**, **`energy_consumed_kwh`**, and **session count**, from `CommissionLedgerEntry` (payout/energy) and franchisee-scoped `Transaction`s (sessions), bucketed on `created_at` (the accrual date the settlements list already uses, so graphs and the settlement table agree).
- A **per-charger breakdown**: payout + kWh per charger over the range.
- **Range presets: 7d / 30d / 3mo / 12mo** (default 30d). **No retention cap** — financial data is never purged (retention only touches `SignalQuality`/`OCPPLog`), so franchisee earnings can look back arbitrarily far.
- **Granularity auto-picks**: **daily** buckets for ranges ≤ 3 months, **monthly** beyond.
- The payout trend counts **non-reversed** entries (settled + pending), so the earnings curve doesn't dip when payouts are merely pending. The settled-vs-pending split is a separate figure in the response (reuse the existing `payout_settled` / `payout_pending` computation).
- `require_franchisee()` scoped; reuses the `date_trunc` bucketing pattern.

## Acceptance criteria

- [ ] Endpoint returns payout, energy, and session-count buckets plus a per-charger breakdown, scoped to the franchisee's chargers
- [ ] Range presets 7d/30d/3mo/12mo supported; default 30d; no upper cap
- [ ] Granularity is daily for ≤3mo and monthly beyond
- [ ] Payout trend uses non-reversed entries; settled-vs-pending returned separately
- [ ] A franchisee cannot see another franchisee's data (ownership scoping enforced)
- [ ] Per-file pytest covers bucketing, granularity switch, franchisee scoping, and empty range

## Blocked by

- None - can start immediately
