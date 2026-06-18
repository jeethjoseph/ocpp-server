# Make Redis charger-removal resilient to DNS/connection loss on deploy

Status: ready-for-agent

Sentry: OCPP-BACKEND-7 — `Failed to remove charger … from Redis: Error -2 connecting to redis:6379. Name or service not known.` (87 occurrences, production)

## What to build

`remove_connected_charger` runs during charger-disconnect cleanup. During a deploy/restart the `redis` hostname can be temporarily unresolvable (DNS `Error -2 … Name or service not known`) or Redis can be briefly unreachable. The cleanup then logs at `error` level, producing 87 prod Sentry events for what is a transient, expected condition while the stack is cycling.

Handle connection/DNS errors from the Redis removal path as a transient, non-error condition: catch them specifically and log at warning (or skip silently during shutdown), distinct from genuinely unexpected Redis failures. The connection-drop case must not surface as a Sentry error.

## Acceptance criteria

- [ ] A DNS/connection failure during `remove_connected_charger` no longer produces a Sentry error event; it logs at warning and returns cleanly.
- [ ] Genuinely unexpected Redis errors (not connection/DNS) still surface for investigation.
- [ ] The return contract (`True`/`False`) is preserved.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s).

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** `remove_connected_charger` now catches `redis.ConnectionError`/`redis.TimeoutError`/`OSError` → `warning` + `return False`; generic `Exception` still `error`. Tests in `test_infrastructure.py` (`test_remove_connected_charger_survives_connection_loss`, `..._reraises_unexpected_as_handled`). Pass.
