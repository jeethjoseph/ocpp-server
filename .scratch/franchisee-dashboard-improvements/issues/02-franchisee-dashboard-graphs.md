# 02 — Franchisee dashboard graphs (reports 1–4)

Status: ready-for-agent

## What to build

Render the four franchisee reports on the existing `/franchisee` dashboard page, below the current count tiles, consuming the analytics endpoint from slice 01.

The four reports:
1. **Payout over time** — franchisee_payout trend (non-reversed).
2. **Energy delivered over time** — kWh per bucket.
3. **Settled vs pending payout** — cashflow split.
4. **Per-charger breakdown** — payout + kWh by charger.

Plus a **range picker** (7d / 30d / 3mo / 12mo, default 30d) that drives the endpoint's range param. Charts via the project's charting library, following the admin-reports chart conventions. Timestamps rendered IST per project convention.

## Acceptance criteria

- [ ] Reports 1–4 render on `/franchisee` below the count tiles
- [ ] Range picker (7d/30d/3mo/12mo) refetches and redraws all graphs
- [ ] Payout trend shows non-reversed earnings; settled-vs-pending shown as its own view
- [ ] Per-charger breakdown shows payout + kWh per charger
- [ ] No Gross figure appears anywhere on the dashboard
- [ ] Bucket labels/dates render in IST
- [ ] `cd frontend && npm run build` passes

## Blocked by

- 01 — Franchisee analytics endpoint (payout/energy/sessions buckets + per-charger)
