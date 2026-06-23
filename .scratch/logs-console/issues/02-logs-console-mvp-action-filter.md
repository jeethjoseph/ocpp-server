# Logs Console MVP — Action filter, end-to-end

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. New GET /api/admin/logs endpoint, /admin/logs page with multi-select Action filter + URL state, Aerich migration 44 (3 indexes). Backend tests in tests/test_logs_console.py (6 passing).

## What to build

The first end-to-end slice of the **Logs Console**: a new admin page at `/admin/logs` that lists **OCPP message log** rows across all chargers, filterable by **OCPP Action**, backed by a new global endpoint.

End-to-end behaviour:

- New `GET /api/admin/logs` endpoint with all-optional query params: `message_type` (multi-valued — comma-joined or repeated; filters server-side via `= ANY()`), `start_date`, `end_date`, `limit`. Returns the row list plus `total`, `has_more`, and summary stats (fold in the shape the retired `/charger/{id}/summary` returned). Newest-first.
- **Date range is always bounded**: when no range is supplied it defaults to the **last 24h**. Never an unbounded query.
- New `/admin/logs` page rendering the row list (reuse the existing OCPP message rendering — Call/CallResult/CallError + action + payload), with a multi-select **Action** control. Action choices come from a **hardcoded canonical OCPP 1.6 action list** on the frontend (BootNotification, StatusNotification, MeterValues, Heartbeat, StartTransaction, StopTransaction, Authorize, DataTransfer, FirmwareStatusNotification, …). Empty selection = all actions.
- Label the control **"Action"**, never "Type".
- **Filter state lives in the URL query string** from the start (so later slices' deep-link works without rework).
- Aerich migration adding indexes `(charge_point_id, timestamp)` and `(message_type, timestamp)` on the `log` table. Confirm the Console query orders/filters on the same time column the `DataRetentionService` cleanup deletes by (`created_at` ≈ `timestamp`, both `auto_now_add`) so the index serves both. See ADR 0014.

Charger / direction / status filters and CSV export arrive in later slices.

## Acceptance criteria

- [ ] `GET /api/admin/logs` returns fleet-wide log rows, filtered by `message_type` (multi) server-side, newest-first
- [ ] Absent date range defaults to last 24h; range and `limit` both honoured
- [ ] Response includes `total`, `has_more`, and summary stats
- [ ] `/admin/logs` page lists rows with the existing message rendering and a multi-select Action filter from a hardcoded OCPP 1.6 list, labelled "Action"
- [ ] Active filters are reflected in the URL query string and restored on load/refresh
- [ ] Aerich migration adds the two composite indexes (generated via Aerich, not hand-written)
- [ ] Backend tests cover action filtering (single, multi, none) and the 24h default window
- [ ] `cd frontend && npm run build` passes

## Blocked by

None - can start immediately.
