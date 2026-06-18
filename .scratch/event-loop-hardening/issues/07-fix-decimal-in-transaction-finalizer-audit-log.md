Status: done

# Fix Decimal-not-JSON-serializable in transaction_finalizer audit log

## Context

Sentry issue **OCPP-BACKEND-Z** ("TypeError: Object of type Decimal is not JSON serializable") fires recurrently on staging. Captured frame vars confirm the cause:

```python
# crud.py log_audit_event args at time of error:
changes = {
    "energy_consumed_kwh": Decimal('3.065'),
    "new_status": "STOPPED",
    "previous_status": "TransactionStatusEnum.SUSPENDED",
    "trigger": "SUSPENDED_TIMEOUT",
}
```

The call site is `backend/services/transaction_finalizer.py:125`:

```python
safe_create_task(log_audit_event(
    action="transaction.finalized",
    entity_type="transaction",
    entity_id=transaction.id,
    actor_type="system",
    changes={
        "previous_status": str(previous_status),
        "new_status": "STOPPED",
        "trigger": stop_reason,
        "energy_consumed_kwh": transaction.energy_consumed_kwh,  # ← raw Decimal
    },
))
```

`AuditLog.changes` is a Tortoise `JSONField`. On `AuditLog.create(...)`, the field's `to_db_value` runs `json.dumps(changes)` which raises `TypeError: Object of type Decimal is not JSON serializable`. The exception is captured by `safe_create_task`'s done-callback and logged (which Sentry's LoggingIntegration then captures as an event), but **the audit row is never written**. The transaction-finalized event is silently missing from the audit trail.

Other audit-log call sites in the same area (e.g., the QR billing audit at `qr_payment_service.py:850-862`) already pre-cast to float — this site was missed.

## What to build

Cast `transaction.energy_consumed_kwh` to `float` at the call site before placing it in the `changes` dict. Match the pattern used elsewhere in the file.

If `energy_consumed_kwh` can be `None` (the model defines it as `DecimalField(..., null=True)` at `models.py:372`), guard with `float(...) if ... is not None else None`.

## What to change

`backend/services/transaction_finalizer.py:125` — change the dict literal so the value is `float(...)`:

```python
changes={
    "previous_status": str(previous_status),
    "new_status": "STOPPED",
    "trigger": stop_reason,
    "energy_consumed_kwh": float(transaction.energy_consumed_kwh) if transaction.energy_consumed_kwh is not None else None,
},
```

While you're in the file, grep for any other `Decimal` values being passed into `log_audit_event` calls — there may be sibling bugs.

## Acceptance criteria

- [ ] `transaction_finalizer.py:125` passes `float(...)` (or `None`) for `energy_consumed_kwh`.
- [ ] Existing tests pass via `docker exec ocpp-backend pytest backend/tests/test_transaction_finalizer.py` (if the file exists) or the closest equivalent.
- [ ] Add or update a test that calls `finalize_stopped_transaction` with a `Decimal` `energy_consumed_kwh` and asserts the `AuditLog` row is created successfully (catches regression).
- [ ] Sentry issue `OCPP-BACKEND-Z` stops accumulating new events post-deploy. Verify by checking the issue's "last seen" timestamp after a few finalizations have run.
- [ ] Audit trail: deliberately trigger a `SUSPENDED_TIMEOUT` finalization on staging, query `audit_log` table, confirm a row with `action='transaction.finalized'` and the energy in `changes` is now present (no errors silently dropped).

## Blocked by

None — can start immediately. Independent of all other issues. One-line fix.
