# Return 504 + suppress Sentry error on RemoteStartTransaction timeout

Status: ready-for-agent

Sentry: OCPP-BACKEND-9 — `HTTPException: Failed to send start command: OCPP timeout: RemoteStartTransaction` (10 occurrences, staging)

## What to build

When an admin triggers a remote start and the charger does not acknowledge `RemoteStartTransaction` within the OCPP timeout, the endpoint raises `HTTPException(status_code=500, …)`. A charger being offline or slow is an expected operational condition, not a server fault — and a 500 captures it as a Sentry error.

Return a 504 (gateway timeout) with a clear, user-facing message indicating the charger did not respond, and ensure the expected timeout case does not generate an error-level Sentry event. Genuine internal failures of the remote-start path should still surface as errors.

## Acceptance criteria

- [ ] An OCPP timeout on remote-start returns HTTP 504 with a clear "charger did not respond" message.
- [ ] The timeout case no longer produces a Sentry error event; non-timeout failures still do.
- [ ] The admin UI's remote-start error handling still renders the message sensibly (no regression on the existing failure path).
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s).

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** `remote_start_charging` returns **504** with "Charger did not respond…" when `send_ocpp_request` reports `OCPP timeout`; other failures still 500. Sentry suppression done by excluding 504 from the Starlette/FastAPI `failed_request_status_codes` in `monitoring_service.py` (504 is the app's only intentional source — noted in the architecture doc). Tests `test_remote_start_timeout_returns_504` + `..._other_failure_returns_500` in `test_chargers.py`; runtime-verified 504 excluded / 500 retained. Pass.

**Decision note:** the issue's two goals (return 504 *and* suppress Sentry) conflict by default, since 504 ∈ Sentry's 5xx reporting range. Resolved by the global `failed_request_status_codes` exclusion rather than a per-request hack. Flag if any other endpoint later needs a genuinely-reported 504.
