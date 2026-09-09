# Runbook: OCPP log retention cleanup times out

**Severity**: P4 (cosmetic — no data or customer impact)
**Owner**: Backend on-call
**Linked alert**: none yet — this runbook exists because the log line reads far
worse than the condition it reports.

---

## Symptom

Once per backend start, and roughly once per 24h thereafter:

```
[ERROR] services.data_retention_service: ❌ Error cleaning up OCPP logs:
Traceback (most recent call last):
  File "/app/services/data_retention_service.py", line 163, in _cleanup_ocpp_logs
  File "/app/services/data_retention_service.py", line 28, in _delete_old_in_batches
  ...
TimeoutError
```

Two details make this look worse than it is:

- **The message is empty.** The handler logs `f"…: {e}"` and `str(TimeoutError())`
  is `''`, so the line ends at the colon and reads like a truncated log.
- **The run still reports success.** The very next line is
  `✅ Data retention cleanup complete: deleted N signal_quality records`,
  because the handler catches the exception and returns `0`.

## What it means

`_cleanup_ocpp_logs` deletes rows from the `log` table older than 90 days, in
batches of `RETENTION_DELETE_BATCH_SIZE` (default 5000). One batch exceeded the
asyncpg pool's `command_timeout` (`DB_COMMAND_TIMEOUT`, default **30s**).

It is a **tail** failure, not a total one. The job deletes most of the day's
backlog and then one late batch times out. As it deletes, it leaves dead tuples
behind; later `SELECT id … WHERE timestamp < cutoff LIMIT 5000` calls have to
scan over that accumulating debris to find live rows, so each batch runs slower
than the last until one crosses 30s.

**Retention is working.** Measured on production 2026-09-09:

| Metric | Value |
|---|---|
| `log` rows | 14,602,401 (~7.2 GB) |
| Oldest row | 2026-06-11 — exactly the 90-day cutoff |
| Rows past cutoff | 4,646 |
| `n_tup_del` | 1,322,263 |
| Ingest rate | ~162,000 rows/day |

The table holds precisely 90 days. The few thousand rows that survive a
timed-out run are cleared by the next one.

## When it's normal

| Scenario | Normal? | Action |
|---|---|---|
| One `TimeoutError` per run, table still ~90 days deep | Yes | None |
| Fires at startup right after a deploy | Yes — the first run has a full day's backlog | None |
| Both staging and production show it | Yes — same pre-existing code path | None |
| `log` oldest row drifting well past 90 days | **No** | Retention is genuinely failing — triage below |
| Table size growing steadily week over week | **No** | Same as above |

## Triage

Confirm retention is still holding the window. Anything near 90 days is fine:

```sql
SELECT min(timestamp) AS oldest,
       count(*) FILTER (WHERE timestamp < now() - interval '90 days') AS past_cutoff
FROM log;
```

Check bloat and whether autovacuum is keeping up:

```sql
SELECT n_live_tup, n_dead_tup, last_autovacuum
FROM pg_stat_user_tables WHERE relname = 'log';
```

On production 2026-09-09 this read 1,261,568 dead tuples with the last
autovacuum on 2026-08-28 — twelve days earlier. That is the underlying driver:
the default `autovacuum_vacuum_scale_factor` of 0.2 means autovacuum will not
trigger until dead tuples reach ~20% of 14.6M ≈ 2.9M rows.

## Mitigation

Nothing is bleeding, so there is nothing to stop. If the noise is unwelcome
before the fix lands, lower the batch size so each delete finishes inside the
timeout:

```
RETENTION_DELETE_BATCH_SIZE=1000
```

More iterations, same total work, each one comfortably under 30s.

## What NOT to do

- **Do not raise `DB_COMMAND_TIMEOUT`** to silence this. That timeout exists
  because of the RDS-restart stale-pool incident ([[adr-0010-db-pool-resilience-rds-restart]]);
  widening it globally to quiet a cleanup job trades a real safety property for
  a cosmetic one.
- **Do not `VACUUM FULL` the `log` table.** It takes an ACCESS EXCLUSIVE lock on
  7 GB and would stall every OCPP message write for the duration.
- **Do not assume retention has failed** because you saw the traceback. Check
  `min(timestamp)` first — the log line does not distinguish "deleted nothing"
  from "deleted 160,000 rows and then ran out of time".

## Customer impact

None. `log` is the OCPP message log behind the Logs Console
([[adr-0014-logs-console-bounded-query-surface]]). No customer surface, billing
path or invoice reads it.

## Escalation

P4. Do not page. Raise to P3 only if `min(timestamp)` drifts past 90 days by
more than a few days, or the table grows week over week — that would mean
retention has stopped making progress rather than merely finishing late.

## Related

- Code: `backend/services/data_retention_service.py`
  (`_delete_old_in_batches`, `_cleanup_ocpp_logs`)
- Pool config: `backend/db_ssl.py` `get_pool_kwargs()` — `command_timeout`
- Tickets: `.scratch/log-retention-timeout/issues/`
- [[adr-0010-db-pool-resilience-rds-restart]] — why the timeout exists
- [[adr-0014-logs-console-bounded-query-surface]] — why the table is large
