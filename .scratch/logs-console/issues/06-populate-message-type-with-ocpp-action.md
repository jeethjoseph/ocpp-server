# Populate `message_type` with the OCPP Action (forward-only)

Status: ready-for-agent

## Parent

`.scratch/logs-console/issues/02-logs-console-mvp-action-filter.md` (the action filter this fix makes actually work)

## What to build

The Logs Console **Action filter** has never returned results, because the ingestion path writes the literal string `"OCPP"` into `OCPPLog.message_type` for every frame — the real **OCPP Action** is only present inside the raw `payload` wire array, never in the column the filter (`message_type__in=...`) and the index `(message_type, timestamp)` rely on. Confirmed on staging: 5.15M `log` rows, all `message_type = "OCPP"` (plus 67 `FirmwareStatusNotification`). Filtering by `StatusNotification`/`MeterValues`/`Heartbeat` returns zero rows while the data is clearly present.

Make ingestion write the **OCPP Action** into `message_type` going forward, so the existing Console filter and per-row display (both already expect Action names matching the frontend `OCPP_ACTIONS` list) start working without any change to the query, schema, or UI.

**Scope decisions already locked (do not re-litigate):**
- **Forward-only.** No backfill. Historical rows keep `message_type = "OCPP"` and age out via the 90-day retention window. The filter simply won't match them — acceptable.
- **Calls only carry an Action.** Derive `message_type` from the raw frame in the WebSocket logging adapter (the ingestion `recv`/`send` wrappers in `connection_manager.py`):
  - **Call** `[2, id, "Action", {…}]` → `message_type = Action` (covers both charger-initiated requests *and* server-initiated commands like `RemoteStartTransaction`).
  - **CallResult** `[3, id, {…}]` → `"CallResult"`; **CallError** `[4, …]` → `"CallError"` (these ack frames carry no Action; **no correlation** to the originating Call).
  - Unparseable / pre-validation / protocol-error frames → keep the `"OCPP"` sentinel.
- Emitted Action strings MUST be exact, case-sensitive matches to the frontend `OCPP_ACTIONS` list (e.g. `StatusNotification`, not `statusnotification`).
- `main.py`'s `FirmwareStatusNotification` log already sets the Action directly — leave it; just ensure the new helper doesn't regress it.

**Blast-radius note (verified):** nothing branches on `message_type == "OCPP"` as a sentinel. The only readers are the Console filter (the beneficiary), the legacy `/api/logs` + charger-detail passthrough, and the `(message_type, timestamp)` index (becomes useful). New Relic metrics are keyed on Actions passed directly in the handlers, **not** on this column — unaffected. Retention is timestamp-only — unaffected. `AuditLog` is a separate concern — untouched.

## Acceptance criteria

- [ ] Newly ingested **Call** frames (both directions) are written with `message_type` set to the OCPP Action from the frame; **CallResult**/**CallError** frames are written as `"CallResult"`/`"CallError"`; unparseable/protocol-error frames keep `"OCPP"`.
- [ ] All ~11 `log_message(...)` ingestion sites in the WebSocket adapter route through the new derivation (no remaining hardcoded `message_type="OCPP"` on valid frames).
- [ ] On the Logs Console, filtering by `StatusNotification` / `MeterValues` / `Heartbeat` returns the matching **newly-ingested** rows; per-row display shows the Action instead of `"OCPP"`.
- [ ] Emitted Action strings are verified to match the frontend `OCPP_ACTIONS` list exactly (case-sensitive).
- [ ] A backend test asserts ingestion writes the Action into `message_type` for a Call frame (and the `CallResult`/`CallError`/sentinel cases); the existing `tests/test_chargers.py` fixture that hardcodes `message_type="OCPP"` is updated.
- [ ] `docs/adr/0014-logs-console-bounded-query-surface.md` and the `CONTEXT.md` "OCPP Action" entry are corrected to state that `message_type` carries the Action **as of this change, forward-only** (historical rows remain `"OCPP"` until retention purges them) — they currently describe this as already-true.
- [ ] No schema change / migration (column already exists); historical rows are intentionally left untouched.

## Blocked by

None - can start immediately.
