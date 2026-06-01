# Modem temperature ingestion, storage, and chart

Status: ready-for-agent

## What to build

Chargers in the fleet send a vendor-extension OCPP `DataTransfer` message (`vendorId=VoltLync`, `messageId=SignalQuality`) every few seconds carrying `rssi`, `ber`, and `temperature`. The handler `_handle_signal_quality` (`backend/main.py:1250`) currently parses `rssi` and `ber` but silently drops `temperature`. Verified on staging on 2026-06-01 — temperature values land in the log as `{"rssi":18,"ber":99,"temperature":38.2,"timestamp":"6870"}`.

Persist the field and surface it on the admin charger detail page (`/admin/chargers/{id}`).

### Backend

- Aerich migration: add nullable `temperature_celsius FLOAT` column to the `signal_quality` table. Generated via `aerich migrate`, not hand-written, per `CLAUDE.md`.
- Update `_handle_signal_quality` to parse `temperature` from the `data` JSON payload and persist it. Treat the field as optional — older firmware or future packets without it should still succeed with `temperature_celsius=NULL`.
- Extend the existing `GET /api/admin/chargers/{id}/signal-quality` response (`backend/routers/chargers.py:962`) with the new `temperature_celsius` field on each row and a `latest_temperature_celsius` on the envelope.

### Frontend

- New "Modem Temperature" card on the charger detail page (`frontend/app/admin/chargers/[id]/page.tsx`), placed near the existing Signal Quality / Status surfaces.
- Recharts line chart, **temperature-only** (RSSI history already has its own surface — do not dual-axis).
- 24h window. Same polling cadence as the existing signal-quality fetch.
- When the latest reading is older than ~5 minutes or null, render a neutral placeholder instead of a stale point.

### Docs

- Write **`docs/adr/0009-modem-temperature-in-signal-quality.md`** capturing the decision to store modem temperature on the `signal_quality` table rather than `meter_value` or a new `charger_telemetry` table. The core reasoning to record: `meter_value` is per-transaction so storing temperature there would lose the idle-state thermal trend (the most useful read for overheating detection); a new dedicated table is the long-term-correct rename but is a refactor, not a feature. Note `signal_quality` is now a misnomer and that a future rename is on the table.
- Add a **CONTEXT.md** entry under "Observability" for `SignalQuality DataTransfer` / `Modem telemetry`, defining the term, noting it carries rssi/ber/temperature, that the table is per-charger (not per-transaction), and that the table name is a known misnomer to resolve later.

## Acceptance criteria

- [ ] Aerich migration adding `temperature_celsius` exists under `backend/migrations/models/` and applies cleanly forward and (sanity-check) backward on a local DB reset.
- [ ] `_handle_signal_quality` persists `temperature` from the payload when present and `NULL` when absent; existing rssi/ber parsing untouched and existing tests pass.
- [ ] `GET /api/admin/chargers/{id}/signal-quality` includes `temperature_celsius` on each historical row and a `latest_temperature_celsius` on the envelope.
- [ ] The new "Modem Temperature" card renders on `/admin/chargers/{id}` with a 24h line chart of temperature values.
- [ ] Chart handles the empty-state (no temperatures yet stored — true for any charger pre-migration) without crashing or rendering a misleading flat line.
- [ ] Stale-data state (latest reading > 5 minutes old, or null) renders a clear placeholder rather than a stale point.
- [ ] `docs/adr/0009-modem-temperature-in-signal-quality.md` exists and explains the trade-off.
- [ ] `CONTEXT.md` has a new entry under Observability for `SignalQuality DataTransfer` / `Modem telemetry`.
- [ ] `cd frontend && npm run build` passes.
- [ ] `docker exec ocpp-backend pytest` passes (baseline flakes excepted per `CLAUDE.md`).
- [ ] Verified on staging: an existing active charger produces non-null temperature readings on the new column within one packet cycle of deploy.

## Blocked by

None — can start immediately.
