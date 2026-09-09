# Fire-and-forget tasks inherit the caller's DB connection and silently lose their write

Status: done

## ELI5

When the server wants to do something without waiting — write an audit row, send a
RemoteStop, start a heartbeat monitor — it hands the job to a background task and moves on.

Those tasks were being handed the caller's *database connection* along with the job. By the
time the task actually ran, the caller had finished with that connection and given it back
to the pool, where someone else picked it up. The task then tried to write down the same
line another request was already using, the database refused, and the task died.

Nobody noticed, because nobody was waiting for it. The request returned 200. The audit row
just never existed.

## What went wrong

`asyncio.create_task` gives the child a copy of the caller's contextvars, and Tortoise keeps
the current DB connection in one of those. So a task spawned inside a transaction inherited
that transaction's pinned `TransactionWrapper`. Since the task runs *later*, the parent had
normally committed and released the connection back to the pool by then:

```
asyncpg.InterfaceError: cannot perform operation: another operation is in progress
  File "/app/crud.py", line 65, in log_audit_event
    return await AuditLog.create(...)
```

**80 occurrences in a single local dev session**, all `log_audit_event`, concentrated at
startup where `data_retention_service`, `billing_retry_service` and `wallet_service` run
concurrently. `billing_retry_service` retries billing inside `@atomic` blocks, which is
exactly the shape that pins a connection.

## Why it mattered more than the error count suggests

The write was **silently** lost. A fire-and-forget task cannot be awaited, so the only trace
is `safe_create_task`'s own error log — every request still returned 200.

An audit trail that drops entries under load is the same defect as one that records events
that never happened, inverted. `ocpp-command-outcome/04` exists because a refused `Reset`
was writing a `charger.reset` row for a reboot that never occurred; the argument there was
that the durable false record is worse than the misleading message, because someone reasons
from it months later. An absent record fails the same way.

Blast radius was wider than audit. All 57 `safe_create_task` call sites were affected,
including the wallet budget-cap RemoteStop dispatch and the OCPP heartbeat monitor. Those
self-heal (energy is monotonic, the next MeterValues tick re-fires), which is likely why the
bug survived unnoticed.

## Root cause, reproduced

Two wrong theories were tried and discarded before this one held — a plain concurrent write
inside a transaction does *not* collide, because `TransactionWrapper` holds a per-instance
`asyncio.Lock` that serialises queries on its connection. The failure needs the parent to
have **finished**:

```
A. task inherits the caller's DB context  -> InterfaceError, audit row LOST
B. task detached into a fresh context     -> no error,        audit row written
```

## The fix

`safe_create_task` passes `context=contextvars.Context()`, so the child resolves a fresh
connection from the pool instead of a stale handle.

This is the correct semantic, not just a workaround: **work that cannot be awaited must not
be enrolled in a transaction whose outcome it cannot observe.** If the caller rolls back, a
fire-and-forget audit row should still exist — it records that the attempt happened.

Trade-off accepted: an empty context also detaches Sentry/New Relic scope, so these tasks
report as their own unit of work rather than as part of the spawning request. Losing
breadcrumb correlation is cheaper than losing the write. Exception reporting is unaffected —
the done-callback runs in the caller's context.

## Acceptance criteria

- [x] A fire-and-forget task spawned inside a transaction completes its write after the
      parent commits and releases the connection.
- [x] The task does not join the caller's transaction — a rolled-back caller does not take
      the write with it.
- [x] Regression tests fail with the fix reverted and pass with it applied (verified both
      directions, not assumed).
- [x] Full backend suite per-file per CLAUDE.md, against the documented baseline.

## Comments

**2026-09-08 — found while log-checking a manual test of the auth-key guard, not by
looking for it.** The auth-key path itself was never at risk: `routers/chargers.py` awaits
`log_audit_event` directly, so a failure there surfaces as a 500 rather than a missing row.
The vulnerable sites are the `safe_create_task(log_audit_event(...))` calls in `main.py` and
`routers/ocpp_ws.py`.

**Not addressed here:** whether audit writes should be fire-and-forget at all. Making them
durable — outbox, or awaited at every call site — is a larger change. This fix removes the
mechanism that was losing them; it does not make the write transactional.
