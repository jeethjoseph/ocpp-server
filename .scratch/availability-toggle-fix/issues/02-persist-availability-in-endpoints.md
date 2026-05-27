Status: ready-for-agent

# Persist `availability` on Accepted in both change-availability endpoints

## What to build

When the OCPP `ChangeAvailability` response is `Accepted` (or `Scheduled`), write the requested `type` to `Charger.availability`. Both endpoints — admin (`routers/chargers.py`) and franchisee (`routers/franchisee_portal.py`) — must do this.

Issue 01 added the column. Issue 02 makes it useful by writing to it. The frontend still reads `latest_status` after this PR — that flip happens in issue 03.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Only update on `Accepted`, ignore `Scheduled` | `Scheduled` means "I'll apply this after my current transaction ends" — the admin intent IS captured; the column should reflect intent, not actuation. UI consumers can join with `latest_status` if they want "in-progress" semantics later |
| Update column BEFORE sending OCPP, roll back on failure | Two-phase complexity for marginal benefit. The Accepted/Scheduled response is fast (typically <1s); waiting for it before persisting is cleaner |
| Update column on `Rejected` too (set back to "previous") | `Rejected` means the charger refused — admin intent didn't take effect, so the column should NOT reflect the requested value. Stays at whatever it was |

## What to change

### `backend/routers/chargers.py` — admin endpoint

In `change_charger_availability` around line 782 (`if success:` block), after the audit log call and before the return statement:

```python
if success:
    ocpp_status = getattr(response, 'status', str(response))

    # Persist admin intent when the charger acknowledged the command.
    # See ADR 0008 for why availability is separate from latest_status.
    from models import ChargerAvailabilityEnum
    if ocpp_status in ("Accepted", "Scheduled"):
        new_availability = (
            ChargerAvailabilityEnum.OPERATIVE
            if type == "Operative"
            else ChargerAvailabilityEnum.INOPERATIVE
        )
        await Charger.filter(id=charger_id).update(availability=new_availability)

    await log_audit_event(
        action="charger.availability_changed",
        entity_type="charger",
        entity_id=charger.charge_point_string_id,
        actor_type="admin",
        actor=admin_user,
        changes={
            "type": type,
            "connector_id": connector_id,
            "ocpp_response": ocpp_status,
            "previous_status": current_status,
            "new_availability": new_availability.value if ocpp_status in ("Accepted", "Scheduled") else None,
        },
    )

    return {
        "success": True,
        "message": "ChangeAvailability command sent",
        "ocpp_response": ocpp_status,
        "type": type,
        "previous_status": current_status,
    }
```

### `backend/routers/franchisee_portal.py` — franchisee endpoint

In `change_availability` around line 269 (`if success:` block), add the same persistence + an audit log entry (currently the franchisee endpoint has no audit logging — fix that too):

```python
if success:
    ocpp_status = getattr(response, 'status', str(response))

    from models import ChargerAvailabilityEnum
    new_availability = None
    if ocpp_status in ("Accepted", "Scheduled"):
        new_availability = (
            ChargerAvailabilityEnum.OPERATIVE if available
            else ChargerAvailabilityEnum.INOPERATIVE
        )
        await Charger.filter(id=charger_id).update(availability=new_availability)

    await log_audit_event(
        action="charger.availability_changed",
        entity_type="charger",
        entity_id=charger.charge_point_string_id,
        actor_type="franchisee",
        actor=franchisee,
        changes={
            "available": available,
            "ocpp_response": ocpp_status,
            "new_availability": new_availability.value if new_availability else None,
        },
    )

    return {"success": True, "message": "Availability changed"}
```

(Add `from crud import log_audit_event` at the top of `franchisee_portal.py` if not already imported.)

### Charger response shape

The admin charger list / detail endpoints already return `charger.__dict__` or similar — verify that `availability` is included in the JSON response. If response shape is filtered via a Pydantic model or explicit dict construction, add `availability` to the response builder.

Grep for the chargers list endpoint and confirm:

```bash
grep -n "@router.get" backend/routers/chargers.py | head -5
```

Check the response shape there. If it's manually constructed, add `availability=_charger.availability.value` (or similar). If it uses `model_to_dict` or a Pydantic auto-serializer, it's already included.

## Tests

Add to an appropriate test file (likely `backend/tests/test_chargers.py` — create if needed, following the project's test conventions):

```python
async def test_change_availability_operative_sets_column(client_admin, test_charger):
    # Mock send_ocpp_request to return Accepted
    with patch("routers.chargers.send_ocpp_request",
               new=AsyncMock(return_value=(True, type("Resp", (), {"status": "Accepted"})()))):
        with patch("routers.chargers.is_charger_connected",
                   new=AsyncMock(return_value=True)):
            resp = await client_admin.post(
                f"/api/admin/chargers/{test_charger.id}/change-availability",
                params={"type": "Operative", "connector_id": 0},
            )
    assert resp.status_code == 200
    refreshed = await Charger.get(id=test_charger.id)
    assert refreshed.availability == ChargerAvailabilityEnum.OPERATIVE


async def test_change_availability_inoperative_sets_column(client_admin, test_charger):
    # same shape but type=Inoperative; assert availability == INOPERATIVE


async def test_change_availability_rejected_does_not_update(client_admin, test_charger):
    # Mock send_ocpp_request to return Rejected
    # The charger should retain its prior availability (Operative default)
    # Confirm audit_log entry was still written with ocpp_response=Rejected
    # and new_availability=None


async def test_change_availability_audit_log_includes_new_availability(client_admin, test_charger):
    # Assert audit_log.changes["new_availability"] == "Inoperative" after Accepted


async def test_franchisee_change_availability_persists(client_franchisee, test_charger):
    # Parallel for the franchisee endpoint
```

Run via:

```bash
docker exec ocpp-backend pytest tests/test_chargers.py -v
```

## Verification

- Migration from issue 01 is applied (`availability` column exists)
- Both endpoints persist on Accepted/Scheduled
- Both endpoints DO NOT persist on Rejected
- Audit log captures `new_availability` field
- Test suite passes; pre-existing baseline flake unchanged
- The frontend toggle STILL reads `latest_status` — no user-visible change yet (issue 03 ships the actual UI fix)

## Definition of done

- Admin + franchisee endpoints both update `Charger.availability` on Accepted/Scheduled responses
- Franchisee endpoint now writes an audit log entry (it didn't before)
- Tests cover Accepted, Rejected, Scheduled, and audit-log-shape cases
- PR merged to `develop`
