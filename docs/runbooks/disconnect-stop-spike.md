# Runbook: Disconnect Stop Spike

**Severity**: P2 (active customer impact — sessions auto-stopping)
**Owner**: Backend on-call (escalate to ops if site-wide)
**Linked alert**: OCPP / Disconnect Stop Spike — `OCPPDisconnectStopped` count > 5 in 10 minutes

---

## Symptom

- **New Relic alert**: `Custom/OCPP/Disconnect/Stopped` count > 5 in 10 minutes
- **Customer reports**: "my session stopped before I was done charging"
- **Audit log**: surge of `transaction.finalized` events with `trigger=DISCONNECT_TIMEOUT`

NRQL:

```sql
SELECT count(*) 
FROM OCPPDisconnectStopped 
SINCE 30 minutes ago 
TIMESERIES 5 minutes
```

## What it means

The disconnect handler is auto-stopping transactions because chargers are
disconnecting and not reconnecting within `DISCONNECT_SUSPEND_TIMEOUT_SECONDS`
(default 180s). Each stop processes wallet billing or QR refunds via
`transaction_finalizer.finalize_stopped_transaction`, so the customer financial
flow has already executed.

This is **expected behavior** for a single charger that loses power. A *spike*
means many chargers are losing connectivity at once, which points to a shared
upstream cause.

## When it's normal

| Scenario | Expected count | Severity |
|---|---|---|
| Single charger with flaky cellular | 1-3 in 10 min | None |
| Site power outage (single station, all chargers) | 5-15 in 10 min | P2 |
| Cellular carrier outage | 20+ in 10 min | P1 |
| Backend regression (config error) | Spike correlated with deploy | P1 |

## Triage

### Step 0 — Pull the affected charger list and group by station

```sql
SELECT count(*) 
FROM OCPPDisconnectStopped 
SINCE 30 minutes ago 
FACET charger_id 
LIMIT 50
```

Then look up which stations:

```bash
ssh ec2-user@app.voltlync.com
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT c.charge_point_string_id, c.latest_status, c.last_heart_beat_time,
          s.id AS station_id, s.name AS station_name
   FROM charger c
   JOIN charging_station s ON c.station_id = s.id
   WHERE c.charge_point_string_id IN ('CP001','CP002','CP003')  -- paste from NRQL
   ORDER BY s.id;"
```

**Branch decision**:
- All affected chargers at **one station** → Step B (site-wide)
- Affected chargers across **many stations** → Step C (platform-wide)
- Single charger dominates the count → Step A (charger-specific)

### Step A — Single charger problem

The most common cause is a flaky cellular modem on a single charger.

```sql
SELECT count(*) 
FROM OCPPDisconnectStopped 
WHERE charger_id = '<charger_id>' 
SINCE 6 hours ago 
TIMESERIES 30 minutes
```

If the disconnect rate has been consistently elevated for hours → physical
hardware or firmware issue. Actions:

1. Pull charger metadata:

   ```bash
   docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
     "SELECT id, charge_point_string_id, latest_status, last_heart_beat_time,
             firmware_version, vendor, model
      FROM charger
      WHERE charge_point_string_id = '<charger_id>';"
   ```

2. Compare firmware version against known-good versions for this vendor.
3. **Mitigation**: contact the site operator and request a manual charger
   reboot. If the issue persists after reboot, flag for site visit.

### Step B — Single station, multiple chargers

Likely a site-wide power or network issue.

1. Pull all chargers at the affected station:

   ```bash
   docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
     "SELECT c.charge_point_string_id, c.latest_status, c.last_heart_beat_time
      FROM charger c
      WHERE c.station_id = <station_id>
      ORDER BY c.last_heart_beat_time DESC;"
   ```

2. **If ALL chargers at the station went offline within a 5-minute window**:
   site power outage. Action: contact site operator. No backend action needed.

3. **If chargers are intermittently dropping** (some online, some offline,
   flapping): ISP or local network issue at the site. Action: contact site
   operator.

4. **Mitigation**: temporarily increase the disconnect timeout to give the
   site more grace while it recovers:

   ```bash
   # Edit /home/ec2-user/ocpp-server/.env
   DISCONNECT_SUSPEND_TIMEOUT_SECONDS=600   # was 180
   docker compose -f docker-compose.prod.yml up -d backend
   ```

   **Revert this once the site recovers** — leaving it at 600 indefinitely
   delays detection of real failures.

### Step C — Platform-wide (many stations affected)

Many stations affected at once → backend or upstream infrastructure problem.

1. Backend health check:

   ```bash
   docker stats --no-stream
   docker compose -f docker-compose.prod.yml ps
   docker exec ocpp-backend curl -s http://localhost:8000/health
   ```

2. WebSocket connection count vs expected:

   ```sql
   SELECT latest(numericValue) 
   FROM Metric 
   WHERE metricName = 'Custom/OCPP/ActiveConnections' 
   SINCE 1 hour ago 
   TIMESERIES 1 minute
   ```

   A sharp drop in active connections, paired with a spike in
   `Custom/OCPP/Heartbeat/Timeouts`, points to backend or network trouble.

3. Postgres health:

   ```bash
   docker exec ocpp-postgres pg_isready
   docker logs ocpp-postgres --tail 100 --since 30m | grep -i -E "error|fatal"
   ```

4. Razorpay webhook delivery — sometimes a webhook storm correlates with
   backend slowness:

   ```bash
   docker logs ocpp-backend --tail 500 --since 30m | grep -i razorpay | head -20
   ```

5. Check nginx (the public-facing layer):

   ```bash
   docker logs ocpp-nginx --tail 200 --since 30m | grep -i error
   ```

6. **Mitigation**: if backend is degraded, restart it gracefully. The startup
   sweep ([stale-suspended-transactions.md](./stale-suspended-transactions.md))
   will catch any transactions stranded by the restart.

## Mitigation cheatsheet

| Cause | Mitigation | Permanent fix |
|---|---|---|
| Single charger flaky modem | Site reboot | Replace modem / SIM |
| Site power outage | Notify site operator | Site repair |
| Cellular carrier issue | Wait, monitor | Multi-SIM failover (long-term) |
| Backend regression | Bump `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` to 600 | Revert deploy |
| Postgres degraded | Restart backend | DB tuning / scale-up |
| Unknown | Bump timeout to 600 to buy time, page senior engineer | Investigate |

## Customer impact

Run this to identify affected customers:

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT t.id, t.user_id, u.email, u.phone_number,
          t.energy_consumed_kwh, t.total_billed, t.end_time
   FROM transaction t
   JOIN app_user u ON t.user_id = u.id
   WHERE t.stop_reason = 'DISCONNECT_TIMEOUT'
     AND t.end_time > NOW() - INTERVAL '1 hour'
   ORDER BY t.end_time DESC;"
```

For QR sessions (anonymous):

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT t.id, qp.customer_vpa, qp.customer_contact, qp.amount_paid,
          qp.refund_amount, qp.status
   FROM transaction t
   JOIN qr_payment qp ON qp.transaction_id = t.id
   WHERE t.stop_reason = 'DISCONNECT_TIMEOUT'
     AND t.end_time > NOW() - INTERVAL '1 hour';"
```

If a customer was billed for a session that they reasonably expected to
continue → manual goodwill credit via the admin panel. Decision threshold:
session length > 5 minutes AND energy delivered < 50% of typical for that
charger.

## What NOT to do

- **Do not** manually mark stopped transactions as RUNNING. Energy has been
  calculated from the last meter value and billing has already run (or failed
  and is in BILLING_FAILED). Reverting the status creates double-billing risk.
- **Do not** disable the disconnect handler. The behavior is correct — we're
  observing reality, not causing it.
- **Do not** restart backend repeatedly hoping it fixes the spike. The chargers
  are reporting the truth. Each restart triggers the stale-suspended sweep,
  adding noise to the investigation.
- **Do not** lower `OCPP_TIMEOUT` to "detect disconnects faster". This makes
  the problem worse by triggering force-disconnect on brief network blips.

## Escalation

| Condition | Action |
|---|---|
| Step A (single charger) | Notify site operator within 1 hour |
| Step B (site-wide) and operator unreachable | Page ops lead within 30 min |
| Step C (platform-wide) | Page backend lead immediately |
| Affected customer count > 10 | Notify customer success within 1 hour |
| Backend memory >90% during incident | Escalate to backend lead |

## Related

- **Code**: `backend/services/disconnect_handler.py` (`_disconnect_suspend_timeout`)
- **Code**: `backend/services/transaction_finalizer.py` (`finalize_stopped_transaction`)
- **Metric**: `Custom/OCPP/Disconnect/Stopped`
- **Event**: `OCPPDisconnectStopped` (fields: `transaction_id`, `charger_id`, `energy_kwh`)
- **Other runbooks**: [zero-energy-stop-spike.md](./zero-energy-stop-spike.md), [stale-suspended-transactions.md](./stale-suspended-transactions.md)
- **Architecture**: `docs/v1/timeout-configuration-guide.md`
