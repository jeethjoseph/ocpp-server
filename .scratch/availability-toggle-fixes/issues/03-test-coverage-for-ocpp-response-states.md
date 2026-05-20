# Test coverage for ChangeAvailability OCPP response states + edge cases

Status: ready-for-agent

## What to build

**M3** — the only existing backend test for the availability toggle (`test_change_availability` in `tests/test_chargers.py:226`) covers a single happy-path case: charger connected + OCPP returns `Accepted`. Three real OCPP response states + the disconnected-charger 409 path + the new connector validation (issue 02) are all untested. Without these, the bugs that issues 01 + 02 are about to fix can silently regress.

### Plan

Add four parametrized / focused tests to `tests/test_chargers.py`. Each follows the pattern of the existing test: mock `main.send_ocpp_request`, drive `connected_charge_points` to simulate connection state, hit the admin endpoint, assert response + audit-log row + (where relevant) the OCPP message dispatched.

1. **`test_change_availability_scheduled_response`** — `send_ocpp_request` returns `(True, {"status": "Scheduled"})`. Backend should return `200`, body includes `ocpp_response: "Scheduled"` and `note: "Scheduled"`. Audit log row records the Scheduled outcome.

2. **`test_change_availability_rejected_response`** — `send_ocpp_request` returns `(True, {"status": "Rejected"})`. Backend should return `200`, body includes `ocpp_response: "Rejected"`. Audit log row records Rejected. (Backend doesn't gate on Rejected — that's by design; frontend handles the UX. The test just pins the contract.)

3. **`test_change_availability_charger_disconnected`** — `connected_charge_points` empty (default), OCPP isn't even called. Backend returns 409 with the "Charger is not connected" detail. `mock_send_ocpp.assert_not_called()` so a regression that bypasses the connection check is caught.

4. **`test_change_availability_rejects_nonzero_connector_id`** — after issue 02 lands, `?connector_id=1&type=Operative` returns 400/422 with the constraint message. OCPP isn't called.

### Audit-log assertion pattern

Existing tests don't assert on the audit log; add an assertion in at least one of the new tests so a future refactor that drops the audit call is caught:

```python
audit_row = await AuditLog.filter(action="charger.availability_changed").order_by("-id").first()
assert audit_row is not None
assert audit_row.changes["ocpp_response"] == "Scheduled"
assert audit_row.changes["previous_status"] == "Available"
```

## Acceptance criteria

- [ ] Four new tests in `tests/test_chargers.py` covering Scheduled, Rejected, disconnected (409), and `connector_id != 0` (422).
- [ ] At least one of the new tests asserts the audit-log row was written with the expected fields (catches a regression where the audit call is dropped).
- [ ] `docker exec ocpp-backend pytest tests/test_chargers.py` passes — total test count goes up by ≥ 4.
- [ ] Full suite remains green.

## Blocked by

Issues 01 and 02 — the new tests assert against the new behavior (post-issue-02 validation + the response branching that issue 01 doesn't change at the backend level but does pin the contract).
