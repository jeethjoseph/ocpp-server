# Public `price_per_kwh` continuity after the tariff rename

Status: ready-for-agent

## What to build

Keep the public stations/map API contract intact through the tariff rename (ADR 0026). The public `StationChargerInfo.price_per_kwh` (GST-exclusive) is a live field consumed by the frontend map/stations pages; the rename must not drop it. Populate it as a nominal excl value derived from `rate_gst_included` (`rate_gst_included / (1 + gst%/100)`, i.e. the back-calculated base rate), and update `compute_station_tariff_range` to range over `rate_gst_included` for the all-in min/max while still emitting the excl `price_per_kwh`. Rename the all-in field name where the public response and `api-services.ts` reference it, keeping `price_per_kwh` present.

## Acceptance criteria

- [ ] Public stations/map response keeps `price_per_kwh` populated (derived from `rate_gst_included`)
- [ ] Station-level min/max range computed over `rate_gst_included`; per-charger `rate_gst_included` exposed under the new name
- [ ] `frontend/lib/api-services.ts` types updated; map + stations pages render unchanged
- [ ] `public_qr_active_sessions` / `public_stations` no longer reference the retired synthetic fee
- [ ] Per-file pytest green (public stations, active sessions); `cd frontend && npm run build` passes

## Blocked by

- 01-rename-tariff-columns-back-calc-base-rate.md
