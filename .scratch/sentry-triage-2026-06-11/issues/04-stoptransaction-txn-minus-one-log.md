# Stop error-logging benign StopTransaction txn=-1

Status: ready-for-agent

Sentry: OCPP-BACKEND-A — `🛑 ❌ Transaction -1 not found` (39 occurrences, production)

## What to build

Some chargers send `StopTransaction` with a placeholder `transaction_id` of `-1` (or another id with no matching DB row) when they have no valid transaction to report. The handler already responds correctly with `id_tag_info={"status": "Invalid"}`, but it logs the miss at `error` level, producing 39 false-alarm Sentry events.

Treat a missing/placeholder transaction on `StopTransaction` as a benign, expected case: downgrade the log to warning (or info for the explicit `-1` sentinel) so it no longer raises a Sentry error. The OCPP response must stay `Invalid` — only the log severity changes.

## Acceptance criteria

- [ ] A `StopTransaction` for a non-existent / `-1` transaction id no longer produces a Sentry error event.
- [ ] The OCPP response remains `id_tag_info={"status": "Invalid"}`.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s).

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** `main.py:874` unknown/placeholder-txn `StopTransaction` downgraded `error`→`warning`; OCPP response stays `Invalid`. New test `test_stop_transaction_handler.py` asserts the `Invalid` response and no ERROR log. Passes.
