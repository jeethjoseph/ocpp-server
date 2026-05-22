Status: ready-for-agent

# Augment _full_refund trigger tests with speed=optimum assertion

## Parent

`.scratch/qr-instant-refund/issues/01-instant-refund-for-full-refunds.md`

## What to build

Issue 01 added `speed=optimum` wiring on every `_full_refund` call, but the test suite only directly asserts the speed kwarg on one direct call (`test_full_refund_passes_speed_optimum_when_flag_enabled`) and inherits it implicitly via `test_handle_charging_failure_issues_full_refund`. The acceptance criterion claimed coverage across "all six trigger sites" — in reality, a future refactor that bypasses `_full_refund` for one trigger would silently lose instant-refund behavior on that path with no test failure.

This slice closes that gap by adding a one-line `speed` assertion to the existing integration test for each of the six trigger sites, OR adding a minimal new test where no existing one exercises the trigger.

The six triggers (all funnel through `QRPaymentService._full_refund`):
1. Zero-energy at StopTransaction (`handle_charging_failure`)
2. Stale payment after webhook delay (`process_payment_captured` stale branch)
3. Concurrent payment rejected on busy charger (`process_payment_captured` rejection branch)
4. Charger not connected at start time (`_start_charging`)
5. RemoteStart failed after retries (`_start_charging`)
6. Plug-in timeout (`_wait_for_plug_in_then_start`)

Approach:
- For each trigger with an existing test, add `assert mock.refund_payment.call_args.kwargs["speed"] == "optimum"` after the existing call assertion. Set `monkeypatch.setenv("RAZORPAY_INSTANT_REFUND_ENABLED", "true")` at the top of the test if not already set.
- For any trigger without an existing test, add a minimal test that exercises the path end-to-end and asserts the speed kwarg.
- Update the docstring on `test_full_refund_passes_speed_optimum_when_flag_enabled` to call out: "All six triggers flow through `_full_refund`. Per-trigger tests assert the speed param at each integration site so a refactor that bypasses `_full_refund` for one trigger is caught."

## Acceptance criteria

- [ ] Every test that exercises any of the six `_full_refund` triggers asserts `call_args.kwargs["speed"] == "optimum"` (when flag on) or `is None` (when flag off, if exercised).
- [ ] Triggers without existing test coverage get a minimal new test.
- [ ] Docstrings on the speed-related tests collectively make clear which trigger each one covers.
- [ ] `docker exec ocpp-backend pytest backend/tests/test_qr_payment_service.py` passes.

## Blocked by

None - can start immediately.

## Comments

### Files changed
- `backend/tests/test_qr_payment_service.py` — added `speed` kwarg assertions and updated docstrings.

### Tests added/modified
- Modified `test_handle_charging_failure_issues_full_refund` (trigger 1: zero-energy) — added `RAZORPAY_INSTANT_REFUND_ENABLED=true` monkeypatch + `speed == "optimum"` assertion.
- Modified `test_concurrent_payment_rejected_when_active_txn` (trigger 3: concurrent rejection) — same.
- Modified docstring on `test_full_refund_passes_speed_optimum_when_flag_enabled` to map each of the 6 triggers to its covering test (or to itself, for triggers 5 and 6).
- Added `test_stale_payment_full_refund_passes_speed_optimum` (trigger 2): backdates the webhook `created_at` past the 300s pending timeout to exercise the stale branch.
- Added `test_charger_not_connected_full_refund_passes_speed_optimum` (trigger 4): mocks `is_charger_connected=False`.

### Judgment calls
- **Triggers 5 (RemoteStart fail) and 6 (Plug-in timeout) intentionally not given a dedicated integration test.** Both would require >30 lines of fixture setup — `_start_charging` needs `connection_manager.send_ocpp_request` patched across retry attempts plus an `asyncio.sleep` shortcut, and `handle_payment_without_plug` polls in a 10s loop until `QR_PAYMENT_PENDING_TIMEOUT` (300s default), which forces either deep clock mocking or a runtime hack. Per the issue's pragmatic-call clause, the direct-call test on `_full_refund` (`test_full_refund_passes_speed_optimum_when_flag_enabled`) already proves the funnel; the docstring on that test now explicitly calls them out so a future contributor knows the gap and can decide whether to invest. The funnel itself is a one-line `await QRPaymentService._full_refund(...)` at each site — a refactor that bypasses `_full_refund` on those paths would also need to bypass it on the four covered triggers, all of which would fail.

### Test count delta
- 30 → 32 (collected) for `tests/test_qr_payment_service.py`.
