# PostBootState — Firmware Specification

**Version**: 1.0
**Date**: 2026-03-24
**Status**: Draft — subject to minor updates after backend implementation

## Overview

After every charger reboot (power outage, firmware update, reset command), the CSMS (Central System) will send a **DataTransfer** message to the charger containing:

1. The **last known energy meter value** (server is the sole source of truth for meter readings)
2. Whether a **charging transaction was in progress** and needs to be resumed

The charger firmware must implement a handler for this incoming DataTransfer message.

---

## OCPP Message Format

### Incoming DataTransfer (Server to Charger)

This message arrives **immediately after** the charger's BootNotification is accepted.

**OCPP wire format:**
```json
[2, "<uniqueId>", "DataTransfer", {
    "vendorId": "VOLTLYNC",
    "messageId": "PostBootState",
    "data": "<JSON string — see payloads below>"
}]
```

### Expected Response (Charger to Server)

```json
[3, "<uniqueId>", {
    "status": "Accepted"
}]
```

If the firmware does not yet support this message, respond with:
```json
[3, "<uniqueId>", {
    "status": "UnknownMessageId"
}]
```

The server handles all response statuses gracefully. No error will occur if the charger rejects.

---

## Payload Variants

### Variant A: Pending Transaction (resume required)

Sent when a charging session was active before the reboot.

```json
{
    "hasPendingTransaction": true,
    "transactionId": 42,
    "startMeterValueWh": 10000,
    "lastMeterValueWh": 15340,
    "energyConsumedWh": 5340
}
```

| Field | Type | Description |
|-------|------|-------------|
| `hasPendingTransaction` | boolean | Always `true` in this variant |
| `transactionId` | integer | The OCPP transaction ID that was in progress |
| `startMeterValueWh` | integer | Meter reading (Wh) when the transaction started |
| `lastMeterValueWh` | integer | Last meter reading (Wh) the server received before reboot |
| `energyConsumedWh` | integer | Energy consumed so far: `lastMeterValueWh - startMeterValueWh` |

### Variant B: No Pending Transaction (meter restore only)

Sent when no charging session was active. The charger just needs its meter value restored.

```json
{
    "hasPendingTransaction": false,
    "lastMeterValueWh": 15340
}
```

| Field | Type | Description |
|-------|------|-------------|
| `hasPendingTransaction` | boolean | Always `false` in this variant |
| `lastMeterValueWh` | integer | Last known meter value (Wh) from the most recent completed transaction. `0` if no transactions have ever occurred on this charger. |

---

## Required Firmware Behavior

### On receiving Variant A (pending transaction)

1. **Set internal energy meter** to `lastMeterValueWh`
2. **Check if EV is still plugged in** (relay/pilot signal)
3. **If EV is plugged in — resume charging:**
   - Resume energy delivery from the `lastMeterValueWh` point
   - Continue sending `MeterValues` messages to the server using `transactionId` from the payload
   - The server will automatically detect the resumed session (no special message needed)
4. **If EV is NOT plugged in — stop the transaction:**
   - Send `StopTransaction` to the server with:
     - `transactionId`: from the payload
     - `meterStop`: the `lastMeterValueWh` value from the payload
     - `reason`: `"PowerLoss"` or `"EVDisconnected"`
   - The server will process billing and refunds

### On receiving Variant B (no pending transaction)

1. **Set internal energy meter** to `lastMeterValueWh`
2. Proceed to normal operation (Available state, ready for new sessions)

### On DataTransfer timeout or no message received

The server sends this message immediately after BootNotification response. If the charger does not receive it within ~15 seconds of BootNotification:

1. **Fallback**: Send a `DataTransfer` request to the server:
   ```json
   {
       "vendorId": "VOLTLYNC",
       "messageId": "GetLastMeterValue",
       "data": "{\"transactionId\": <id>}"
   }
   ```
   This is the existing pull-based mechanism and remains fully supported.
2. If the charger doesn't know the transaction ID, it can send `GetLastMeterValue` without a transaction ID — the server will respond with the latest data for this charger.

---

## Sequence Diagrams

### Flow 1: Reboot with Active Transaction (Resume)

```
Charger                          Server (CSMS)
  |                                  |
  |--- BootNotification ----------->|  (charger rebooted)
  |                                  |  Server suspends transaction #42
  |<-- BootNotification.conf -------|  (status: Accepted)
  |                                  |
  |<-- DataTransfer (PostBootState) |  hasPendingTransaction: true
  |    transactionId: 42             |  lastMeterValueWh: 15340
  |--- DataTransfer.conf ---------->|  status: Accepted
  |                                  |
  |  [Charger sets meter to 15340]   |
  |  [Charger checks EV plugged in]  |
  |  [EV IS plugged in → resume]     |
  |                                  |
  |--- MeterValues (txn 42) ------->|  Server auto-resumes: SUSPENDED → RUNNING
  |--- MeterValues (txn 42) ------->|  Normal charging continues
  |    ...                           |
```

### Flow 2: Reboot with Active Transaction (Can't Resume)

```
Charger                          Server (CSMS)
  |                                  |
  |--- BootNotification ----------->|
  |<-- BootNotification.conf -------|
  |                                  |
  |<-- DataTransfer (PostBootState) |  hasPendingTransaction: true
  |    transactionId: 42             |  lastMeterValueWh: 15340
  |--- DataTransfer.conf ---------->|  status: Accepted
  |                                  |
  |  [Charger sets meter to 15340]   |
  |  [Charger checks EV plugged in]  |
  |  [EV NOT plugged in → stop]      |
  |                                  |
  |--- StopTransaction ------------>|  transactionId: 42
  |    meterStop: 15340              |  reason: EVDisconnected
  |<-- StopTransaction.conf --------|
  |                                  |  Server processes billing + refund
```

### Flow 3: Reboot with No Transaction (Meter Restore)

```
Charger                          Server (CSMS)
  |                                  |
  |--- BootNotification ----------->|
  |<-- BootNotification.conf -------|
  |                                  |
  |<-- DataTransfer (PostBootState) |  hasPendingTransaction: false
  |    lastMeterValueWh: 15340       |
  |--- DataTransfer.conf ---------->|  status: Accepted
  |                                  |
  |  [Charger sets meter to 15340]   |
  |  [Ready for new sessions]        |
```

---

## Edge Cases

| Scenario | Firmware Behavior |
|----------|-------------------|
| **Multiple rapid reboots** | Each boot will receive a PostBootState. Use the latest one. Data is idempotent. |
| **PostBootState not received (timeout)** | Use GetLastMeterValue fallback after 15 seconds. |
| **`lastMeterValueWh` is 0** | This is a brand new charger with no history. Set meter to 0. |
| **EV plugged in but can't charge** (fault) | Send `StopTransaction` with reason `"Other"` and `meterStop = lastMeterValueWh`. Then send `StatusNotification` with the fault details. |
| **Server sends multiple PostBootState** (shouldn't happen, but defensive) | Process each one. Last one wins. |

---

## Testing

The backend team will provide a simulator at `backend/simulators/ocpp_simulator_post_boot_state.py` that demonstrates the full flow. Firmware team can use it as a reference implementation.

---

## Identification

- **vendorId**: `VOLTLYNC` (used for all custom VOLTLYNC DataTransfer messages)
- **messageId**: `PostBootState` (this specific feature)
- **Existing messageId**: `GetLastMeterValue` (pull-based fallback, still supported)
- **Existing vendorId for signal quality**: `JET_EV1` (unchanged, separate feature)
