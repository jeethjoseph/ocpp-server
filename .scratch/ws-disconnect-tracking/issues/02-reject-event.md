Status: ready-for-agent

# OCPPWebSocketRejected event for connect-time rejects

## Context

`routers/ocpp_ws.py` rejects WebSocket connection attempts in two paths today:

1. **Tombstone reject** (`ocpp_ws.py:43-51`) — charger tried to reconnect within ~100ms of a previous close. WS closed with code 1013.
2. **Validation reject** (`ocpp_ws.py:61-71`) — `charge_point_string_id` not registered in the DB. WS closed with code 1008.

Both already emit `log_audit_event(action="charger.connection_rejected", ...)`, so the audit trail exists. They are **not** disconnects (the WS never reached `cp.start()`), so they don't flow through `force_disconnect` and won't be captured by Issue 01's `OCPPWebSocketDisconnect` event.

Rejects matter for diagnosis: a charger that fails validation repeatedly indicates a misconfigured / decommissioned charger trying to reconnect; a charger hitting the tombstone repeatedly indicates a reconnect storm or network-edge weirdness. Neither is visible in NR today.

## What to build

Both reject paths in `ocpp_ws.py` emit one `OCPPWebSocketRejected` NR custom event AND increment `Custom/OCPP/Rejects/<reject_reason>` for 13-month retention.

Event attributes:

- `charger_id` — the OCPP `charge_point_string_id` from the URL (may not exist in DB on validation reject — that's the whole point of validation reject)
- `reject_reason` — one of `tombstone`, `validation_failed`
- `ws_close_code` — `1013` for tombstone, `1008` for validation
- `tombstone_remaining_ms` — only set when `reject_reason = 'tombstone'`; the `remaining_ms` value computed at `ocpp_ws.py:42`

Emit before the `websocket.close(...)` call so the event is recorded even if the close itself fails.

## Acceptance criteria

- [ ] `OCPPMetrics.record_websocket_rejected(...)` added in `services/monitoring_service.py`, emits the event AND increments the per-reason counter
- [ ] Both reject paths in `routers/ocpp_ws.py` call `record_websocket_rejected` before `websocket.close(...)`
- [ ] Manual test: send a connect attempt for an unregistered `charge_point_string_id`, observe `OCPPWebSocketRejected` with `reject_reason=validation_failed` and `ws_close_code=1008` in NR
- [ ] Manual test: trigger a tombstone reject (force-disconnect then reconnect within 100ms via simulator), observe `OCPPWebSocketRejected` with `reject_reason=tombstone`, `ws_close_code=1013`, non-null `tombstone_remaining_ms`
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` mention the reject event alongside the disconnect event
- [ ] `docker exec ocpp-backend pytest` passes

## Out of scope

- Dashboard panel for rejects → Issue 03
- Alert on validation_failed spike (a misconfigured deploy could flood) — wait for baseline data

## Blocked by

None — can be implemented in parallel with Issue 01. (Both touch `monitoring_service.py` so expect a merge conflict on that file if both PRs are open at the same time; resolution is mechanical.)
