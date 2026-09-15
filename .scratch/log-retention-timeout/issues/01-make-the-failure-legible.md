# Make the retention failure legible

Status: ready-for-agent

## What to build

The OCPP log retention job fails once per run with a traceback whose message is
**empty**, immediately followed by a line claiming the run succeeded. That
combination cost a real investigation on 2026-09-09 during a deploy, because
the log gives an on-call engineer no way to tell "deleted nothing" from
"deleted 160,000 rows and then ran out of time".

Nothing is broken underneath — see `docs/runbooks/log-retention-timeout.md` for
the evidence that retention is holding its 90-day window. This ticket is
entirely about the signal.

Three changes, all in `backend/services/data_retention_service.py`:

1. **Log the exception type.** The handler logs `f"…: {e}"`, and
   `str(TimeoutError())` is `''`, so the line ends at a colon. Include
   `type(e).__name__` so the next occurrence explains itself. Apply to every
   `except` in the service, not just the OCPP-log one — they share the defect.

2. **Stop reporting success when a sub-task failed.** The run emits
   `✅ Data retention cleanup complete: deleted N signal_quality records` even
   when OCPP log cleanup raised. Track per-task failures and say so.

3. **Treat a timed-out batch as "enough for this run", not an error.** A
   `TimeoutError` inside `_delete_old_in_batches` means the loop got through
   most of the backlog and should stop cleanly, returning the count deleted so
   far. The next run continues from there — which is already what happens, just
   via an exception path that looks like a fault. Catch it in the loop and
   break; let anything else propagate.

Do NOT raise `DB_COMMAND_TIMEOUT` to make this go away. That timeout exists
because of the RDS stale-pool incident ([[adr-0010-db-pool-resilience-rds-restart]]);
widening a real safety property to quiet a cleanup job is the wrong trade.

## Acceptance criteria

- [ ] A failing cleanup logs the exception class; `TimeoutError` no longer appears as an empty message.
- [ ] A run where one sub-task fails does not log a bare success line — the summary names the failure.
- [ ] A batch timeout returns the partial count and stops the loop, rather than raising out of `_delete_old_in_batches`.
- [ ] Any other exception still propagates to the handler and is logged with its type.
- [ ] A test covers the partial-progress path: given a timeout on the third batch, the function returns the rows deleted by batches one and two.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

None — can start immediately.
