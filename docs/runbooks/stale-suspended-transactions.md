# Runbook: Stale Suspended Transactions Sweep

**Severity**: P3 (informational at low counts, P2 if recurring)
**Owner**: Backend on-call
**Linked alert**: OCPP / Stale Suspended Sweep — `OCPPStaleSuspendedSwept` event with `count > 0`

---

## Symptom

One or more of these fires shortly after a backend startup:

- **Log line**: `🧹 Found N stale suspended transaction(s) — cleaning up`
- **New Relic event**: `OCPPStaleSuspendedSwept` with `count > 0`
- **Counter**: `Custom/OCPP/Suspended/StaleSwept` increments by N

NRQL to view recent sweeps:

```sql
SELECT count, timestamp 
FROM OCPPStaleSuspendedSwept 
SINCE 24 hours ago
```

## What it means

The `disconnect_handler.sweep_stale_suspended_transactions()` function runs
once at backend startup. It looks for transactions stuck in SUSPENDED status
with `suspended_at` older than `max(DISCONNECT_SUSPEND_TIMEOUT_SECONDS,
SUSPEND_TIMEOUT_SECONDS) + 60s` (default: 540s) and finalizes them via
`transaction_finalizer.finalize_stopped_transaction`.

Stale rows mean the previous backend process was holding in-memory timeout
tasks that died with the process — usually a crash, OOM, deploy, or non-graceful
restart. The sweep is the safety net.

## When it's normal

| Scenario | Expected count | Action |
|---|---|---|
| Planned deploy via `docker compose up -d backend` | 0–5 | None — graceful shutdown drains most timers |
| `docker restart ocpp-backend` | 0–10 | None |
| Server reboot | 0–20 | None — depends on traffic at the moment |
| **First startup of the day, no recent deploy** | **Any count** | **Investigate — see triage** |
| **Recurring sweeps within 1 hour** | **Any** | **Investigate — see triage** |
| **N > 20 single sweep** | | **P2 — escalate to backend lead** |

## Triage

### Step 1 — How many were swept and which transactions?

NRQL:

```sql
SELECT count, timestamp 
FROM OCPPStaleSuspendedSwept 
SINCE 30 minutes ago
```

### Step 2 — Was there a recent crash, OOM, or planned restart?

```bash
ssh ec2-user@app.voltlync.com

# Container restart history
docker inspect ocpp-backend --format '{{.State.StartedAt}}'
docker inspect ocpp-backend --format 'restarts: {{.RestartCount}}'

# Check exit code from previous run
docker inspect ocpp-backend --format 'last exit: {{.State.ExitCode}}'

# OOM kills in dmesg
sudo dmesg | grep -i -E "killed process|out of memory" | tail -20
```

| Exit code | Meaning | Action |
|---|---|---|
| 0 | Graceful shutdown | Sweep is benign — no action |
| 137 | SIGKILL | Likely OOM — see Step 3 |
| 143 | SIGTERM | Graceful — sweep is benign |
| Other non-zero | Crash | Check Sentry — see Step 4 |

### Step 3 — If OOM suspected, check memory pressure

```bash
docker stats ocpp-backend --no-stream
free -h
```

If backend memory is consistently >80% of the container limit, raise the limit
in `docker-compose.prod.yml`:

```yaml
backend:
  deploy:
    resources:
      limits:
        memory: 2G   # was 1G
```

### Step 4 — If no OOM, check Sentry for exceptions in the startup window

Sentry filter:
- Project: `ocpp-server-backend`
- Time range: `<container start time> ± 5 minutes`
- Search: `is:unresolved`

Most likely candidates:
- `tortoise.exceptions.OperationalError` — DB connection issue at startup
- `redis.exceptions.ConnectionError` — Redis not yet ready when backend started
- Anything in `main.py:startup_event`

### Step 5 — Confirm the sweep actually finalized the transactions

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT id, transaction_status, suspended_at, end_time, stop_reason, total_billed
   FROM transaction
   WHERE stop_reason = 'STALE_SUSPEND_SWEEP'
   ORDER BY end_time DESC
   LIMIT 20;"
```

All swept transactions should have `transaction_status = STOPPED` (or
`BILLING_FAILED` if billing errored), and `stop_reason = STALE_SUSPEND_SWEEP`.

## Mitigation

Self-heals on backend startup. **No manual intervention needed** for the
typical case.

If a sweep keeps recurring at every restart, the underlying issue is the
*restarts*, not the sweep. Fix the crash root cause (Step 3 / 4).

## Customer impact

If the sweep finalized transactions that customers were actively using:

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT t.id, t.user_id, u.email, u.phone_number,
          t.energy_consumed_kwh, t.total_billed, t.end_time
   FROM transaction t
   JOIN app_user u ON t.user_id = u.id
   WHERE t.stop_reason = 'STALE_SUSPEND_SWEEP'
     AND t.end_time > NOW() - INTERVAL '1 hour'
   ORDER BY t.end_time DESC;"
```

If energy was actually delivered (`energy_consumed_kwh > 0`), billing has
already run via `WalletService.process_transaction_billing` — the customer was
charged correctly. No goodwill credit needed.

If the customer reports their session ended unexpectedly, point them at the
relevant `WalletTransaction` row to confirm billing was applied.

## What NOT to do

- **Do not** manually flip swept transactions back to `RUNNING`. Energy has
  been calculated and billing has run. Reverting will create double-bill risk.
- **Do not** disable `sweep_stale_suspended_transactions` to silence the alert.
  It's the safety net — silencing it leaves orphaned rows in SUSPENDED forever.
- **Do not** restart the backend repeatedly hoping it clears the alert. Each
  restart triggers the sweep again, generating more alerts.

## Escalation

| Condition | Action |
|---|---|
| Single sweep, count ≤ 5, recent deploy | None — informational |
| Single sweep, count > 20 | Escalate to backend lead within 1 hour |
| Recurring sweeps (>2 in one hour) | Escalate to backend lead within 30 min |
| Any swept transaction has `BILLING_FAILED` status with `energy_consumed_kwh > 0` | Escalate to backend lead — manual billing review needed |

## Related

- **Code**: `backend/services/disconnect_handler.py` (`sweep_stale_suspended_transactions`)
- **Code**: `backend/services/transaction_finalizer.py` (`finalize_stopped_transaction`)
- **Metric**: `Custom/OCPP/Suspended/StaleSwept`
- **Event**: `OCPPStaleSuspendedSwept`
- **Triggered from**: `backend/main.py` startup_event
- **Other runbooks**: [disconnect-stop-spike.md](./disconnect-stop-spike.md) — if the swept transactions correlate with disconnect events
