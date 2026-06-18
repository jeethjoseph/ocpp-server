Status: ready-for-agent

# OCPPWebSocketDisconnect event end-to-end

## Context

VoltLync chargers appear to disconnect from the CSMS more often than expected, but disconnect events are not currently persisted anywhere queryable — only emitted to container stdout as `[DISCONNECT]` log lines and rotated out within days. New Relic is already wired (`services/monitoring_service.py` has `MetricsCollector.record_event` / `record_metric`), but no disconnect-specific event is emitted today.

This issue introduces a single canonical NR custom event `OCPPWebSocketDisconnect` so the team can baseline disconnect frequency, categorise root causes, and decide whether the `OCPP_TIMEOUT=120s` heartbeat threshold needs tuning.

Framing: this is an **investigative campaign**, not permanent monitoring infrastructure. Retention is NR-only (8–30 days); no DB table is added. After 1–2 weeks of baseline data, SLO thresholds will be set bottom-up from the observed distribution.

## What to build

Every WebSocket disconnect from the OCPP server emits exactly one `OCPPWebSocketDisconnect` NR custom event AND increments a per-category counter metric (`Custom/OCPP/Disconnects/<category>`) for 13-month retention.

The event has these attributes:

**Core (mandatory)**
- `charger_id` — the OCPP `charge_point_string_id`
- `disconnect_category` — one of `client_close`, `server_error`, `stale_replaced`, `heartbeat_timeout`, `ops_initiated`
- `duration_seconds` — wall-clock from WS accept to disconnect
- `ws_close_code` — WebSocket close code if known (1000/1001/1006/1011/etc.), else null
- `ws_close_reason` — close-frame reason string if present, else empty
- `had_active_transaction` — boolean, true if a `Transaction` was in `PENDING_START` or `RUNNING` for this charger at disconnect time
- `reason_text` — the existing free-text reason string passed into `force_disconnect` (disambiguates within a category)

**Forensics**
- `transaction_id` — the active transaction's id if `had_active_transaction = true`, else null
- `heartbeat_seconds_since_last` — seconds between last inbound OCPP message and disconnect
- `messages_received` — count of valid inbound OCPP messages received on this WS session

## Category mapping

`force_disconnect` in `core/connection_manager.py` is the chokepoint — every disconnect flows through it. Map the existing `reason` strings to categories via a small dispatch dict:

| `reason` string passed today | Category |
|---|---|
| `"Natural WebSocket disconnect"` | `client_close` |
| `"WebSocket session ended"` (from generic exception in `ocpp_ws.py`) | `server_error` |
| `"New connection attempt - replacing stale connection"` | `stale_replaced` |
| `"OCPP activity timeout (<N>s)"` (from heartbeat_monitor) | `heartbeat_timeout` |
| Anything from ChangeAvailability, manual admin force-disconnect, etc. | `ops_initiated` |
| Anything else | `ops_initiated` (fallback) — log a warning so unmapped reasons get noticed |

The heartbeat_monitor reason string may need to be stabilised so the prefix match is reliable.

## Required supporting changes

1. **Cache Charger row metadata on `connection_data` at WS accept** — extend `validate_and_connect_charger` (or call site) to return the Charger object, then keep references needed for the disconnect event without a fresh DB lookup on the disconnect path. (Even though no cohort attrs are in the schema for now, this prep is cheap and avoids hot-path DB IO later.)

2. **Track `active_transaction_id` on `connection_data`** — set in the `StartTransaction` handler in `main.py`, clear in the `StopTransaction` handler. Used by `had_active_transaction` and `transaction_id` attrs. No DB lookup on disconnect.

3. **Track `messages_received` counter on `connection_data`** — increment in `core/connection_manager.py` when a valid inbound OCPP message passes validation (the `log_message(..., status="received", ...)` call site at line ~499).

4. **Glossary update in `CONTEXT.md`** — add a new `### Observability` subheading with three entries: **OCPP message log**, **Audit event**, **NR custom event**. Distinguishes the three things currently called "event" in the codebase. Wording finalised during the grill-with-docs session.

5. **Docs update** per CLAUDE.md — update `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` to reflect the new event type and the observability glossary section.

## Acceptance criteria

- [ ] `OCPPMetrics.record_websocket_disconnect(...)` added in `services/monitoring_service.py`, emits the custom event AND increments the per-category counter
- [ ] `force_disconnect` in `core/connection_manager.py` calls `record_websocket_disconnect` after every cleanup, with the correct `disconnect_category` resolved from the existing `reason` string
- [ ] All 5 categories observable in NR after a manual test (force-disconnect one charger, kill the WS from server, trigger heartbeat timeout, admin-initiated disconnect, simulate `cp.start()` exception)
- [ ] `had_active_transaction` returns `true` when disconnect occurs mid-charge and `false` otherwise; verified by starting a transaction and force-disconnecting the charger
- [ ] `messages_received` reflects the actual number of valid OCPP messages on the session
- [ ] `heartbeat_seconds_since_last` matches the observed gap in container logs
- [ ] CONTEXT.md has the new `### Observability` section with three terms
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated
- [ ] No new DB queries on the disconnect path (verified by reading the diff — all event attrs come from `connection_data` or the WS close frame, none from `await Model.get(...)`)
- [ ] `docker exec ocpp-backend pytest backend/tests/test_*websocket*.py backend/tests/test_*connection*.py` passes (or new tests added if coverage is missing)

## Out of scope (deferred)

- `OCPPWebSocketRejected` for tombstone/validation rejects → Issue 02
- NR dashboard, alert policy, notification destination → Issue 03
- SLO thresholds — wait for baseline data (7–14 days post-deploy)
- `OCPP_TIMEOUT=120s` tuning — wait for the `heartbeat_seconds_since_last` histogram
- Cohort attributes (vendor, firmware, station, franchisee) — explicitly cut during the grill; revisit if data motivates

## Blocked by

None — can start immediately.
