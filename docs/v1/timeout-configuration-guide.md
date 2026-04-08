# Timeout Configuration Guide

All timeouts are configured via environment variables. Defaults are production-ready but can be tuned per deployment.

---

## OCPP_TIMEOUT

**Default:** `120` seconds
**File:** `backend/core/connection_manager.py`

How long the server waits without any OCPP message (heartbeat, meter values, status notification) before considering a charger dead. The heartbeat monitor runs every 15 seconds and checks `last_seen` against this threshold.

**When it triggers:** Charger loses network, power failure, firmware crash.
**What happens:** Server calls `force_disconnect()` — cleans up WebSocket, removes from Redis, cancels heartbeat task, and suspends any active transactions.

**Tuning:**
- Chargers typically send heartbeats every 30-60s. Set this to 2-3x the heartbeat interval.
- Too low: false disconnects during brief network blips.
- Too high: stale connections linger, delayed transaction suspension.

---

## SUSPEND_TIMEOUT_SECONDS

**Default:** `300` seconds (5 minutes)
**File:** `backend/main.py`, `backend/services/disconnect_handler.py`

After a charger reboots (sends BootNotification) with an ongoing transaction, the transaction is suspended. This timeout controls how long the server waits for the charger to resume the transaction before auto-stopping it.

**When it triggers:** Charger firmware reboot, soft/hard reset command.
**What happens:** Transaction moves from SUSPENDED to STOPPED, energy is calculated from the last meter value, and wallet billing is applied.

**Tuning:**
- Charger boot times vary by manufacturer (10s to 3 minutes).
- Set to at least 2x the slowest charger's boot time.
- Too low: transactions get stopped before the charger finishes rebooting.
- Too high: users wait longer for billing on genuinely dead sessions.

---

## DISCONNECT_SUSPEND_TIMEOUT_SECONDS

**Default:** `180` seconds (3 minutes)
**File:** `backend/services/disconnect_handler.py`

After `OCPP_TIMEOUT` fires and a charger is force-disconnected, active transactions are suspended. This timeout controls how long the server waits for the charger to reconnect before auto-stopping the suspended transaction.

**When it triggers:** After `OCPP_TIMEOUT` detects silence and suspends transactions.
**What happens:** If the charger reconnects (sends BootNotification) within this window, the timeout resets and the transaction can resume. If the timeout expires, the transaction is auto-stopped with reason `DISCONNECT_TIMEOUT`, energy is calculated, and billing is applied.

**Tuning:**
- Urban stations (reliable power): 120-180s is fine.
- Highway/rural stations (power fluctuations): consider 300-600s.
- Too low: transactions stopped during brief power outages that would have self-resolved.
- Too high: users see "Charging" for too long after a real failure.

**Relationship:** This timer starts *after* `OCPP_TIMEOUT` fires. Total time from power loss to auto-stop = `OCPP_TIMEOUT` + `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` (default: 120 + 180 = 300s / 5 min).

---

## SOCKET_GRACE_PERIOD_SECONDS

**Default:** `300` seconds (5 minutes)
**File:** `backend/main.py`

When a socket-type charger (no cable lock) reports `Available` status while a transaction is running, it may mean the user temporarily unplugged. This grace period gives the user time to plug back in before the transaction is marked as failed.

**When it triggers:** StatusNotification `Available` received for a charger with an active transaction.
**What happens:** Transaction continues running during the grace period. If the charger reports `Charging` again (or MeterValues arrive), the grace period is cancelled. If the timer expires, the transaction is marked as FAILED.

**Tuning:**
- Socket chargers (Type 2 without lock): 180-300s is typical.
- Tethered chargers (with cable lock): this scenario is rare; default is fine.
- Too low: legitimate brief unplugs (repositioning cable) kill the session.
- Too high: abandoned sessions stay open too long.

---

## ZERO_ENERGY_TIMEOUT_SECONDS

**Default:** `120` seconds (2 minutes)
**File:** `backend/services/zero_energy_watchdog.py`

If a running transaction receives meter values where the energy register (`Energy.Active.Import.Register`) hasn't increased for this duration, the server sends `RemoteStopTransaction` to the charger.

**When it triggers:** Charger is connected and sending meter values, but no energy is being delivered. Common causes: EV battery full and not communicating stop, faulty connector contact, EVSE relay stuck open, EV-side charging error.
**What happens:** Server sends `RemoteStopTransaction`. Charger responds with `StopTransaction`. Normal billing follows.

**Tuning:**
- Chargers typically send meter values every 10-30s. Set to at least 4x the meter interval to avoid false positives.
- Too low: false stops during brief charging pauses (EV battery balancing, thermal throttling).
- Too high: wasted station time on genuinely stalled sessions.

**Relationship:** Works together with `ZERO_ENERGY_GRACE_PERIOD_SECONDS` — the grace period must elapse before this check activates.

---

## ZERO_ENERGY_GRACE_PERIOD_SECONDS

**Default:** `60` seconds (1 minute)
**File:** `backend/services/zero_energy_watchdog.py`

After a transaction starts, EVs negotiate charging parameters (EVSE handshake, current limits, battery state). During this period, the energy register may not advance. This grace period prevents false positives during startup.

**When it triggers:** Ignored — this is a suppression window, not a trigger.
**What happens:** Zero-energy checks are skipped for this duration after `StartTransaction`.

**Tuning:**
- Most EVs start drawing power within 5-30s of plug-in.
- Older or slower EVs may take up to 60s.
- Too low: false stops on slow-negotiating vehicles.
- Too high: genuinely stalled sessions take longer to detect (total detection time = grace + timeout).

**Total detection time:** `ZERO_ENERGY_GRACE_PERIOD_SECONDS` + `ZERO_ENERGY_TIMEOUT_SECONDS` (default: 60 + 120 = 180s / 3 min from transaction start).

---

## RETENTION_DAYS

**Default:** `90` days
**File:** `backend/main.py`

How long to keep historical signal quality data and OCPP logs before the data retention service deletes them.

**Tuning:**
- Regulatory requirements may dictate minimum retention.
- More data = more disk usage. Signal quality records can accumulate fast (one per minute per charger).

---

## CLEANUP_INTERVAL_HOURS

**Default:** `24` hours
**File:** `backend/main.py`

How often the data retention background task runs to delete old records.

**Tuning:**
- Daily (24h) is fine for most deployments.
- High-volume deployments (100+ chargers) may benefit from 12h or 6h intervals.

---

## Quick Reference

| Variable | Default | Unit | Purpose |
|---|---|---|---|
| `OCPP_TIMEOUT` | 120 | seconds | Heartbeat inactivity → charger dead |
| `SUSPEND_TIMEOUT_SECONDS` | 300 | seconds | Reboot resume window |
| `DISCONNECT_SUSPEND_TIMEOUT_SECONDS` | 180 | seconds | Reconnect window after disconnect |
| `SOCKET_GRACE_PERIOD_SECONDS` | 300 | seconds | Unplug grace for socket chargers |
| `ZERO_ENERGY_TIMEOUT_SECONDS` | 120 | seconds | Stalled energy → auto-stop |
| `ZERO_ENERGY_GRACE_PERIOD_SECONDS` | 60 | seconds | Startup negotiation grace |
| `RETENTION_DAYS` | 90 | days | Data retention period |
| `CLEANUP_INTERVAL_HOURS` | 24 | hours | Retention cleanup frequency |

## Timeline: What Happens During a Power Failure

```
T+0s     Charger loses power, stops sending messages
T+120s   OCPP_TIMEOUT fires → force_disconnect()
           → Transaction SUSPENDED
           → DISCONNECT_SUSPEND_TIMEOUT starts (180s)
T+300s   DISCONNECT_SUSPEND_TIMEOUT expires
           → Transaction auto-stopped
           → Energy calculated, billing applied
```

## Timeline: What Happens During a Stalled Charge

```
T+0s     Transaction starts (StartTransaction)
T+0-60s  ZERO_ENERGY_GRACE_PERIOD — checks skipped
T+60s    Grace period ends, zero-energy monitoring begins
T+60s+   Meter values arrive but energy register unchanged
T+180s   ZERO_ENERGY_TIMEOUT fires (60s grace + 120s stall)
           → RemoteStopTransaction sent
           → Charger stops, normal billing follows
```
