# 03 — Reports tab shell + Temperature subreport chart

Status: done

## What to build

The admin **Reports** surface and its first subreport (Temperature), end-to-end against the aggregation endpoint from slice 02.

- **Nav + route**: add a top-level "Reports" entry to the admin sidebar (`adminItems` in `app/admin/layout.tsx`, lucide icon) and a `/admin/reports` route.
- **Framework shell**: a subreport tab strip at `/admin/reports` — Temperature active; Energy/kWh, Signal quality, Sessions/revenue present as disabled "coming soon" stubs so the framework is visible and future subreports drop in cleanly.
- **Temperature subreport page**: charger selector + IST-correct date-range picker with presets (24h / 7d / 30d / 90d / custom) built on `lib/date-presets.ts` (`istToday()`), custom range **hard-capped at 90 days** (disable selection beyond). Recharts chart rendering the **avg line with a shaded min–max band**. Show the envelope (overall min/avg/max, latest) in a header readout.
- **Data layer**: TanStack Query hook in `lib/queries/` + api-service function in `lib/api-services.ts`, mirroring the existing `useSignalQuality` pair. Historical data — refetch on param change, no short polling interval.

## Acceptance criteria

- [ ] "Reports" appears in the admin sidebar and routes to `/admin/reports`
- [ ] Subreport tab strip shows Temperature (active) + Energy/Signal/Sessions (disabled stubs)
- [ ] Temperature page has a charger selector and IST date-range presets (24h/7d/30d/90d/custom)
- [ ] Custom range cannot be set beyond 90 days
- [ ] Chart shows the avg line with a shaded min–max band, fed by the slice-02 endpoint
- [ ] Query hook + api-service follow the existing `lib/queries` / `lib/api-services` convention
- [ ] `cd frontend && npm run build` passes (full production build, per project convention)

## Blocked by

- 02 — Temperature aggregation endpoint (hourly/daily min-avg-max buckets)

## Comments

**2026-09-01 — reconciled to `done` by tracker audit.** Still marked open long after the
work shipped; the tracker had no close ritual, so the status was never moved back.
Verified by locating the artifact this issue specifies in the live repo: `frontend/app/admin/reports/page.tsx` + temperature subreport

Method and caveats: `.scratch/tracker-reconciliation/REPORT.md`.
