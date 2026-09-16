# SessionLimit — Firmware Specification

**Version**: 1.0 · **Date**: 2026-09-15 · **Status**: CSMS side shipped; firmware pending sign-off (ADR 0031, offline-continuity issues 04 and 07)

## Overview

The CSMS pushes each transaction's **energy budget** to the charger, and the charger enforces it **locally** — online or offline. This is the precondition for offline continuity: a charger that keeps the contactor closed through a CSMS outage with no local limit delivers unbounded free energy.

OCPP 1.6 has no per-transaction energy limit (`SetChargingProfile` constrains power over time, `MaxEnergyOnInvalidId` is charge-point-wide), so this is a vendor `DataTransfer`. Field names mirror the OCPP 2.1 `TransactionLimit` construct so a later migration is a transport swap.

The CSMS keeps its own server-side check as a redundant failsafe. **Whichever enforcer fires first wins.** Duplicate stops are harmless.

## Message: SessionLimit (CSMS → charger)

Sent **immediately after `StartTransaction.conf`**, and again on every WebSocket connect for any transaction the CSMS still considers open. May be re-sent at any time with a new value.

```json
[2, "<uniqueId>", "DataTransfer", {
    "vendorId":  "VOLTLYNC",
    "messageId": "SessionLimit",
    "data": "{\"transactionId\": 8814, \"maxEnergy\": 22000, \"maxCost\": null, \"maxTime\": null}"
}]
```

`data` is a JSON **string** (OCPP 1.6 `DataTransfer.data` is a string).

| Field | Type | Meaning |
|---|---|---|
| `transactionId` | int | The id from `StartTransaction.conf`. **The limit is keyed on this, never on `idTag`.** |
| `maxEnergy` | int, Wh | **Total** energy this transaction may deliver, counted from `meterStart`. The whole current limit, never an increment. |
| `maxCost`, `maxTime` | null | Reserved. Ignore. |

### Required charger behaviour

1. **Match on `transactionId`.** If it equals the active transaction, store the limit and reply `Accepted`. If there is no active transaction or the id differs, reply `Rejected`. Firmware without support replies `UnknownMessageId`; the CSMS handles all three gracefully.
2. **Enforce locally:** when `(current register − meterStart) ≥ maxEnergy`, open the contactor and stop the transaction. No CSMS involvement, no network needed.
3. **Persist across reboots**, together with `transactionId` and `meterStart`, with the same torn-write durability as the stored meter value (rotate across slots, checksum, take the newest valid on boot). A power cut mid-session must not lose the cap.
4. **Absolute, idempotent, re-sendable.** A repeat with the same value changes nothing. A repeat with a new value **replaces** the stored one — it may be higher (a same-payer top-up) or lower.
5. **No limit received, then link lost:** if connectivity is lost for the active transaction before any `SessionLimit` has been accepted for it, the charger must **open the contactor as today**. Continuity applies only to a capped transaction. (The gap is one round trip after `StartTransaction.conf`; this rule closes it.)
6. **Reconnect:** expect a re-assert within seconds of the WebSocket opening, before or after `BootNotification`. Treat it per rule 1.

## Message: StopDetail (charger → CSMS)

OCPP 1.6 has no `StopTransaction.reason` for "budget reached". A stop caused by the local limit therefore uses `reason: "Local"` and is followed by:

```json
[2, "<uniqueId>", "DataTransfer", {
    "vendorId":  "VOLTLYNC",
    "messageId": "StopDetail",
    "data": "{\"transactionId\": 8814, \"reason\": \"SessionLimit\"}"
}]
```

Send it **after** `StopTransaction` (queue it as transaction-related if offline). The CSMS replies `Accepted`, or `Rejected` for an unknown transaction; either way the charger needs no further action. Without it, a budget stop is indistinguishable from a customer pressing stop.

`reason` values today: `SessionLimit`. Others may be added; the CSMS stores whatever it receives (≤ 50 chars).

## Sequence

```
CSMS → charger   RemoteStartTransaction
charger → CSMS   StartTransaction {idTag, meterStart}
CSMS → charger   StartTransaction.conf {transactionId}
CSMS → charger   DataTransfer SessionLimit {transactionId, maxEnergy}     ← store + Accepted
charger → CSMS   MeterValues ×N (online, or queued while offline)
                 … session energy ≥ maxEnergy: contactor opens locally …
charger → CSMS   StopTransaction {reason: "Local", meterStop}
charger → CSMS   DataTransfer StopDetail {transactionId, reason: "SessionLimit"}
```

## Edge cases the CSMS relies on

- A `SessionLimit` for a transaction the charger has already stopped → `Rejected`. Harmless.
- The CSMS may also send `RemoteStopTransaction` for the same reason around the same time (the server-side failsafe). Accept it; a second stop is a no-op.
- Internal-role (operator) sessions receive **no** `SessionLimit`. With no cap, rule 5 applies if the link drops: open the contactor.
- **No local start path.** Today a session can only begin with `RemoteStartTransaction`, which an offline charger cannot receive — that is what makes offline *start* impossible. If firmware ever adds a local start path (RFID reader, plug-and-charge, start button), it must ship with `AllowOfflineTxForUnknownId` and `LocalAuthorizeOffline` held `false` and the CSMS team must be told, so the server-side assertion can be built. The CSMS does not set per-charger configuration.

## CSMS reference

`backend/services/session_limit_service.py` (compute, push, outcome classification), `ChargePoint.after_start_transaction` / `reassert_session_limits`, `ChargePoint._handle_stop_detail` in `backend/main.py`. Simulator: `backend/simulators/ocpp_simulator_production.py` (`handle_data_transfer`, `enforce_session_limit`).
