# 02 — Temperature aggregation endpoint (hourly/daily min-avg-max buckets)

Status: ready-for-agent

## What to build

A backend endpoint that returns modem/board temperature aggregated into time buckets for a single charger over a date range — the data source for the Temperature subreport.

Temperature readings live in the `signal_quality` table (`temperature_celsius`, nullable, indexed `created_at`, `charger` FK), written from OCPP `DataTransfer/SignalQuality` packets. Aggregate them:

- New aggregation service that buckets rows by time using parameterized raw SQL `date_trunc`, returning `bucket_start`, `min`, `avg`, `max`, and `sample_count` for non-null `temperature_celsius`, scoped by `charger_id` and time range.
- **Auto-granularity**: hourly buckets for ranges ≤ 7 days, daily for longer.
- **90-day hard cap**: reject or clamp ranges whose start is older than 90 days (retention floor).
- New admin router `GET /api/admin/reports/temperature` (params: `charger_id` required, plus range as `start`/`end` or `days`; optional granularity override). Returns the bucketed series plus an envelope (overall min/avg/max + latest reading). Registered in `main.py`, guarded by `require_admin`, prefix `/api/admin/reports`.

Follow the aggregation approach recorded in the ADR (01). Keep functions under 40 lines per project convention.

## Acceptance criteria

- [ ] `GET /api/admin/reports/temperature` returns bucketed `{bucket_start, min, avg, max, sample_count}` series for a charger + range
- [ ] Buckets are hourly for ranges ≤ 7 days and daily beyond
- [ ] Null `temperature_celsius` rows are excluded from aggregation
- [ ] Ranges older than 90 days are capped/rejected consistently with the ADR
- [ ] Endpoint is admin-only (`require_admin`) and registered in `main.py`
- [ ] Raw SQL is parameterized (no string interpolation of user input)
- [ ] Per-file pytest covers bucketing correctness, empty range, null exclusion, and the granularity switch

## Blocked by

- 01 — ADR: Reports framework + time-bucketing aggregation pattern
