# Pre-deploy blockers: revert M4 audit "fix" + replace generic Pydantic 422 with named constraint

Status: ready-for-agent

## What to build

Two pre-deploy blockers surfaced in the senior-engineer review of issues 01 + 02. Both must land before the availability-toggle work goes to staging.

### Revert the M4 "audit race" change

Issue 02 moved the `previous_status` snapshot from BEFORE the OCPP exchange to AFTER, using `refresh_from_db`. The reasoning was wrong — Python is synchronous within an await; the local `current_status = charger.latest_status` capture from the in-memory model is frozen at the moment of assignment regardless of concurrent DB writes. There is no race window for the local variable.

The change introduces a real regression: if the change is `Accepted` and the charger immediately fires a `StatusNotification` reflecting the new state, the post-OCPP `refresh_from_db` reads the NEW state and audit-logs it as `previous_status`. Operator reading the audit later sees "the charger was already Unavailable when I made it Unavailable" — nonsensical.

Restore the snapshot pattern: capture `current_status = charger.latest_status` after the DB fetch, before the connection check. Audit + response use that frozen value as `previous_status`.

### Replace generic Pydantic 422 with a named-constraint HTTPException

Issue 02 used `Query(..., ge=0, le=0)` to enforce whole-charger semantics. Pydantic enforces it but emits a generic message:

```
"Input should be less than or equal to 0"
```

…which gives an ops user no idea WHY zero is the only allowed value. The acceptance criterion was *"with a message naming the constraint."*

Replace with an explicit in-handler check:

```python
if connector_id != 0:
    raise HTTPException(
        status_code=422,
        detail="connector_id must be 0 — admin availability toggle operates "
               "at whole-charger granularity. Per-connector control is not "
               "exposed via the admin API.",
    )
```

The `Query` constraint can stay as `ge=0` (still defensive) but drop `le=0`. The clear-message check carries the semantic weight.

## Acceptance criteria

- [ ] `previous_status` in the admin endpoint's response + audit-log row reflects the charger's state BEFORE the OCPP exchange (i.e., the moment the operator clicked the button).
- [ ] No `refresh_from_db` call between the OCPP send and the audit write.
- [ ] `POST /api/admin/chargers/{id}/change-availability?type=Operative&connector_id=1` returns 422 with a detail string that explicitly mentions "whole-charger" or equivalent — not the generic Pydantic "less than or equal to 0".
- [ ] `connector_id=0` still works.
- [ ] Existing `test_change_availability` passes.
- [ ] Full backend suite green.

## Blocked by

None — can start immediately. Blocks staging deploy of the availability-toggle work.
