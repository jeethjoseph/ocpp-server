# 04 — Temperature report CSV export

Status: ready-for-agent

## What to build

CSV export for the Temperature subreport, so an admin can download the aggregated series for the selected charger and range.

- **Backend**: `GET /api/admin/reports/temperature/export` streaming CSV, reusing the same aggregation as slice 02 and the streaming pattern from `routers/logs.py` (`StreamingResponse`, `csv_safe_cell`). Columns: `bucket_start_ist, min_celsius, avg_celsius, max_celsius, sample_count`. Timestamps converted to IST via `to_ist(...).isoformat()` so cells carry the unambiguous `+05:30` offset. Admin-only, honors the same 90-day cap.
- **Frontend**: a download button on the Temperature subreport page that requests the export for the current charger + range selection.

## Acceptance criteria

- [ ] `GET /api/admin/reports/temperature/export` streams a CSV of the bucketed series
- [ ] Columns are `bucket_start_ist, min_celsius, avg_celsius, max_celsius, sample_count` with the `*_ist` naming convention
- [ ] `bucket_start_ist` cells carry the `+05:30` IST offset (asserted in a test)
- [ ] Export honors the same 90-day cap and `require_admin` guard as the data endpoint
- [ ] Download button on the Temperature page exports the current charger + range selection
- [ ] `cd frontend && npm run build` passes

## Blocked by

- 02 — Temperature aggregation endpoint (hourly/daily min-avg-max buckets)
- 03 — Reports tab shell + Temperature subreport chart
