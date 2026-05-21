# Runbook: Zero Energy Stop Spike

**Severity**: P3 (P2 if widespread or correlated with firmware update)
**Owner**: Backend on-call (escalate to OEM relations if firmware regression)
**Linked alert**: OCPP / Zero Energy Stop Spike — `OCPPZeroEnergyStopped` count > 3 in 10 minutes

---

## Symptom

- **New Relic alert**: `Custom/OCPP/ZeroEnergy/Stopped` count > 3 in 10 minutes
- **Customer reports**: "I plugged in but it never started charging" or "it stopped after a few seconds"
- **Audit log**: `transaction.finalized` events with energy_consumed_kwh near zero

NRQL:

```sql
SELECT count(*) 
FROM OCPPZeroEnergyStopped 
SINCE 1 hour ago 
TIMESERIES 5 minutes
```

## What it means

The `zero_energy_watchdog` service monitors active transactions for stalled
energy consumption. If the energy register hasn't advanced for
`ZERO_ENERGY_TIMEOUT_SECONDS` (default 7200s / 2h since 2026-05-21; was 120s
prior) after the grace period (`ZERO_ENERGY_GRACE_PERIOD_SECONDS`, default
60s), it auto-stops the session by sending `RemoteStopTransaction` to the
charger.

**Note on alert thresholds**: with the 2h timeout, a single spike is unusual —
each stop now represents either a real taper-completed EV that idled for 2h+
or a chronically stuck charger. The historical 120s baseline meant frequent
benign stops on taper-end; do not transfer those volume assumptions forward.

A *spike* means many sessions are failing to deliver energy, which points to
**one of three patterns**:

1. **Charger meter regression** (firmware update broke the meter reading)
2. **Vehicle BMS issue** (the EV is rejecting charge negotiation)
3. **Watchdog config too aggressive** (slow AC chargers ramping up beyond
   the timeout window)

The triage is fundamentally different from disconnect-stop because there's no
network/power issue — the charger is online and reporting MeterValues, just
with the same kWh value over and over.

## When it's normal

| Scenario | Expected count | Severity |
|---|---|---|
| Single occasional vehicle handshake failure | 1-2 in 1 hour | None |
| Slow AC charger with cold-soaked EV battery | 1-3 in 30 min | None |
| New charger model rolled out | 5+ in 1 hour | P3 — investigate firmware |
| Spike correlated with firmware push | Surge after firmware update timestamp | P2 — likely regression |

## Triage decision tree

```
Pull affected charger model+firmware FACET
  ├─ Single model+firmware dominates → Step A (firmware regression)
  ├─ Multiple models, single vehicle make → Step B (vehicle BMS)
  └─ Mixed, no clear pattern             → Step C (config or grid-level)
```

### Step 0 — Pull the affected charger and vehicle data

```sql
SELECT count(*) 
FROM OCPPZeroEnergyStopped 
SINCE 1 hour ago 
FACET charger_id 
LIMIT 50
```

Cross-reference to chargers and recent transactions:

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT c.charge_point_string_id, c.vendor, c.model, c.firmware_version,
          COUNT(*) AS stopped_count
   FROM transaction t
   JOIN charger c ON t.charger_id = c.id
   WHERE t.stop_reason IN ('RemoteStop', 'DeAuthorized', 'Other', 'EmergencyStop')
     AND t.end_time > NOW() - INTERVAL '1 hour'
     AND (t.energy_consumed_kwh IS NULL OR t.energy_consumed_kwh < 0.1)
   GROUP BY c.charge_point_string_id, c.vendor, c.model, c.firmware_version
   ORDER BY stopped_count DESC;"
```

### Step A — Single charger model + firmware dominates

Likely a firmware regression. Common pattern: a vendor pushed an update and the
new firmware mis-reports the energy register.

1. Confirm the firmware version is recently deployed:

   ```bash
   docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
     "SELECT firmware_version, COUNT(*), MIN(updated_at), MAX(updated_at)
      FROM charger
      WHERE vendor = '<vendor>' AND model = '<model>'
      GROUP BY firmware_version;"
   ```

2. Check OCPP logs for any one affected session — look for repeated identical
   `MeterValues` payloads:

   ```bash
   docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
     "SELECT timestamp, payload
      FROM ocpp_log
      WHERE charge_point_string_id = '<charger_id>'
        AND message_type = 'MeterValues'
        AND timestamp > NOW() - INTERVAL '30 minutes'
      ORDER BY timestamp DESC
      LIMIT 20;"
   ```

   If the `Energy.Active.Import.Register` value is identical across multiple
   meter values from the same session, the meter is stuck.

3. **Mitigation options**:
   - **If firmware was just pushed**: roll back via the admin firmware
     management panel
   - **If rollback not possible**: temporarily increase
     `ZERO_ENERGY_TIMEOUT_SECONDS` (default 7200 / 2h) to suppress further
     auto-stops while you wait for a vendor fix. Pick a value larger than the
     longest plausible firmware-induced stall:
     ```bash
     # Edit /home/ec2-user/ocpp-server/.env.prod
     ZERO_ENERGY_TIMEOUT_SECONDS=14400   # was 7200 — also bump Redis TTL in code if you go above 14400
     docker compose -f docker-compose.prod.yml up -d backend
     ```
     **Invariant**: keep the value strictly less than the Redis state TTL in
     `redis_manager.set_zero_energy_state` (currently 14400). If you need a
     value ≥ 14400, raise the TTL in code first or stall detection breaks
     silently across charger reconnects.
   - **Long-term**: flag the vendor and capture an OCPP log sample for the
     firmware ticket

### Step B — Multiple chargers, single vehicle make

Less common but possible. The affected sessions are likely from one make/model
of EV that's struggling to handshake with the charger.

1. Cross-reference affected sessions to vehicles:

   ```bash
   docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
     "SELECT vp.make, vp.model, COUNT(*) AS failed_sessions
      FROM transaction t
      JOIN app_user u ON t.user_id = u.id
      JOIN vehicle_profile vp ON vp.user_id = u.id
      WHERE t.stop_reason IN ('RemoteStop', 'DeAuthorized', 'Other')
        AND t.end_time > NOW() - INTERVAL '1 hour'
        AND (t.energy_consumed_kwh IS NULL OR t.energy_consumed_kwh < 0.1)
      GROUP BY vp.make, vp.model
      ORDER BY failed_sessions DESC;"
   ```

2. **Mitigation**: no backend action. Notify customer success — affected users
   may need to use a different charger type (AC vs DC) or a different connector.

### Step C — Mixed pattern, no clear cause

If neither A nor B explains it, suspect:

1. **Watchdog config drift**: was `ZERO_ENERGY_TIMEOUT_SECONDS` recently
   lowered (default is 7200)? Check `.env` against git history.

   ```bash
   cd /home/ec2-user/ocpp-server
   git log -p .env | head -50
   ```

2. **Tariff misconfiguration**: a tariff with `rate_per_kwh = 0` would not
   trigger zero-energy stops directly, but it could mask billing failures
   that look similar to operators.

3. **Backend regression**: was the watchdog code recently changed?

   ```bash
   cd /home/ec2-user/ocpp-server
   git log --oneline backend/services/zero_energy_watchdog.py | head -10
   ```

4. **Mitigation**: if no clear cause, raise the timeout temporarily and page
   backend lead. Default is 7200 (2h); double it if a real bug needs cover:

   ```bash
   ZERO_ENERGY_TIMEOUT_SECONDS=14400
   docker compose -f docker-compose.prod.yml up -d backend
   ```
   See the invariant note in Step A about Redis TTL before going higher.

## Customer impact

These customers had sessions auto-stopped without delivering energy, so they
should NOT have been billed:

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT t.id, t.user_id, u.email, u.phone_number,
          t.energy_consumed_kwh, t.total_billed, t.end_time, t.stop_reason
   FROM transaction t
   JOIN app_user u ON t.user_id = u.id
   WHERE t.end_time > NOW() - INTERVAL '1 hour'
     AND (t.energy_consumed_kwh IS NULL OR t.energy_consumed_kwh < 0.1)
   ORDER BY t.end_time DESC;"
```

`total_billed` should be NULL for all of these (no energy = no charge). If
any have `total_billed > 0` while `energy_consumed_kwh < 0.1` → escalate, this
is a billing bug.

For QR sessions, the full prepayment should have been refunded automatically:

```bash
docker exec ocpp-postgres psql -U ocpp_user -d ocpp_db -c \
  "SELECT t.id, qp.amount_paid, qp.refund_amount, qp.status
   FROM transaction t
   JOIN qr_payment qp ON qp.transaction_id = t.id
   WHERE t.end_time > NOW() - INTERVAL '1 hour'
     AND (t.energy_consumed_kwh IS NULL OR t.energy_consumed_kwh < 0.1);"
```

If `qp.status` is not `REFUNDED` for any of these → manual refund via Razorpay
admin or admin panel.

## What NOT to do

- **Do not** disable the watchdog. A genuine stall = wasted charging slot =
  lost revenue + frustrated customer at the next session.
- **Do not** raise `ZERO_ENERGY_TIMEOUT_SECONDS` to or beyond the Redis state
  TTL (`set_zero_energy_state` in `redis_manager.py`, currently 14400s) without
  also raising the TTL. If timeout ≥ TTL, the Redis state can expire mid-stall
  on a silent charger and the watchdog will never trip — stall detection
  silently disabled.
- **Do not** mark affected transactions as COMPLETED — they had no energy
  delivered, COMPLETED would imply billable.
- **Do not** roll back firmware without checking which other deployments might
  depend on the new version.

## Escalation

| Condition | Action |
|---|---|
| Step A — confirmed firmware regression | Page backend lead + flag OEM relations |
| Step B — single vehicle make | Notify customer success — no engineering action |
| Step C — config drift | Revert config + page backend lead |
| Customer reports billing for zero-energy session | P1 — escalate immediately, billing bug |

## Related

- **Code**: `backend/services/zero_energy_watchdog.py`
- **Code**: `backend/services/transaction_finalizer.py`
- **Metric**: `Custom/OCPP/ZeroEnergy/Stopped`
- **Event**: `OCPPZeroEnergyStopped` (fields: `transaction_id`, `charger_id`, `stalled_seconds`)
- **Config**: `ZERO_ENERGY_TIMEOUT_SECONDS`, `ZERO_ENERGY_GRACE_PERIOD_SECONDS` in `.env`
- **Other runbooks**: [disconnect-stop-spike.md](./disconnect-stop-spike.md) — different symptom (network), different triage
- **Architecture**: `docs/v1/timeout-configuration-guide.md`
