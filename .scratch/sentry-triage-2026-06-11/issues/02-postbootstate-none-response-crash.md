# Null-check PostBootState response before reading .status

Status: ready-for-agent

Sentry: OCPP-BACKEND-1Q — `AttributeError: 'NoneType' object has no attribute 'status'` (32 occurrences, staging)

## What to build

`_push_post_boot_state` sends a `DataTransfer(message_id="PostBootState")` call to the charger and immediately reads `response.status`. When the charger's reply cannot be parsed into a response object (connection dropped mid-call, malformed reply), the OCPP `call()` resolves to `None`, and `response.status` raises `AttributeError`, which then surfaces as an error-level Sentry event.

Handle the `None` response explicitly: log it as a warning (charger did not return a usable PostBootState response) and return without crashing, the same way the existing `asyncio.TimeoutError` branch is handled. The happy path (`status == "Accepted"`) and the non-accepted-status warning should remain unchanged.

## Acceptance criteria

- [ ] A `None` response from the PostBootState call no longer raises `AttributeError`; it logs a warning and returns cleanly.
- [ ] `status == "Accepted"` and non-accepted statuses behave exactly as before.
- [ ] Test covers the `None`-response path for `_push_post_boot_state`.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s).

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** Added `if response is None:` guard in `_push_post_boot_state` (logs warning, returns) before reading `.status`. Test `test_post_boot_state.py::TestPushPostBootStateErrorHandling::test_none_response`. `docker exec ocpp-backend pytest tests/test_post_boot_state.py` passes.
