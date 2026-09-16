# Offline Continuity — Required Changes (v1.0)

**Date**: 2026-09-15
**Audience**: Firmware team
**Decision record**: ADR 0031 (charger-authoritative offline session). Wire contract for the cap: `session-limit-spec.md`.
**Status**: CSMS side built for every item below except the retirement of `PostBootState` (gated on your rollout). This document is for a review meeting, not a sign-off by email — four items differ from your HLD, and each difference exists because the HLD version fails in a specific way we can name.

## The short version

Today the charger opens the contactor when the OCPP WebSocket drops. We want it to **keep charging** through a CSMS outage, queue its transaction messages, and replay them when the link returns. Six things have to be true for that to be safe, and one of them — the local energy cap — is not optional: **continuity and the cap ship in the same firmware release, never separately.**

| ID | Requirement | vs. HLD |
|---|---|---|
| R1 | Hold the contactor on WebSocket loss; queue and replay transaction messages | Agreed |
| R2 | Enforce `SessionLimit.maxEnergy` locally, keyed on `transactionId` | **HLD keys on `idTag` — change** |
| R3 | Never report a cumulative reading lower than one already reported for the transaction | **HLD promises the register won't reset — change** |
| R4 | Torn-write durability for persisted transaction state | **New** |
| R5 | Metering state is never overwritten by diagnostic buffering | Agreed (small) |
| R6 | Name the retry cadence by the standard keys; values stay fleet-wide | **HLD hardcodes — minor** |
| R7 | No local start path without telling us | New, informational |

## What already works — please don't regress it

- **Queued `MeterValues` arrive with their original timestamps.** We store the frame's `timestamp` beside receipt time (migration 62). Keep stamping frames when they are taken, not when they are sent. A frame with no timestamp, or one more than 5 minutes in the future, is stored without a measured time — so a wrong clock degrades gracefully, but a right one is worth a lot.
- **`StopTransaction` after an outage.** Our stop handler now refuses to move money for a session we already closed (see "What changes on our side"), so a late stop is safe. Send it; don't suppress it.
- **`PostBootState` still arrives after every `BootNotification` during the rollout — new firmware must reply `Accepted` and then IGNORE the meter value in it.** The message exists only because today's firmware cannot remember its own meter. Firmware that satisfies R3/R4 holds better data than we do: our pushed value is the last reading *we* saw, which after an outage is stale by exactly the energy you delivered offline. Applying it would reintroduce the R3 failure from the server side. Accept it (so old and new firmware look the same to us), apply nothing, and keep reporting from your own persisted register. This is what lets new firmware run against the unchanged server, and it is why there is no cutover: the push is harmless noise to new units and a lifeline to old ones, until the fleet is uniform and we delete it.

## R1 — Hold the contactor on WebSocket loss

Connectivity loss alone never opens the contactor and never triggers a reset. Local safety supervision — earth fault, leakage, over/under voltage, over-current — is untouched and continues to stop the charge through its existing paths. The only thing suppressed is a reset whose sole cause is that the CSMS is unreachable.

While offline, queue **transaction-related** messages (`StartTransaction`, `MeterValues` carrying a `transactionId`, `StopTransaction`, and the vendor `StopDetail`) and deliver them **in chronological order** on reconnect, per OCPP 1.6 §4.x offline behaviour. Non-transaction messages (`Heartbeat`, `StatusNotification`) may be dropped or coalesced.

**Failure it prevents:** a customer's overnight charge ending because a cellular modem lost signal. On this fleet 41% of reconnects arrive via `BootNotification` and site power events routinely take three chargers down together.

**What we do with the replay:** the first replayed frame resumes the session on our side; we bill the true delivered energy from the replayed readings. If the charger stays silent for **48 hours** (latched connectors) or **12 hours** (unlatched), we close the session on the last reading we saw, refund the customer on that basis, and treat the rest as written off. Anything you replay after that is recorded but no longer billed.

## R2 — Enforce the cap locally, keyed on `transactionId` (change from HLD)

Full contract in `session-limit-spec.md`. The essentials:

- After `StartTransaction.conf` we send `DataTransfer VOLTLYNC/SessionLimit {transactionId, maxEnergy}`. `maxEnergy` is the **total** energy this transaction may deliver, counted from `meterStart`, in whole Wh. It is the whole current limit, never an increment; a repeat replaces the stored value.
- When `(register − meterStart) ≥ maxEnergy`, open the contactor and send `StopTransaction reason=Local` followed by `DataTransfer StopDetail {transactionId, reason: "SessionLimit"}`.
- Reply `Accepted` when the id matches the active transaction, `Rejected` otherwise. We re-send on every reconnect; expect it.
- **If the link drops before any `SessionLimit` has been accepted for the active transaction, open the contactor as today.** Continuity applies only to a capped transaction.

**Why `transactionId`, not `idTag`:** the HLD keys the limit on `idTag`. On our platform `idTag` is a per-**customer** value minted once and reused for every session that customer ever has. It cannot identify a session, and against a limit persisted in EEPROM across reboots the ambiguity gets worse: a reboot could revive last week's cap for today's session. `transactionId` is unique per session by construction.

**Failure it prevents:** a charger delivering unbounded free energy while unreachable. This is the precondition for R1, not a peer feature.

## R3 — Never report a reading lower than one already reported (change from HLD)

The HLD promises the register will not reset within a transaction. It cannot: an **involuntary** reset is what happens when the meter chip loses power, and a site power cut resets the register and drops the link in the same event. Only a *deliberate* reset (commissioning, meter swap) can be constrained to "no open transaction".

So the requirement is stated about the **wire**, not the hardware: for a given `transactionId`, no `MeterValues` or `StopTransaction` reading may be lower than any reading already sent for it. The register may reset; the firmware must reconstruct the true cumulative value from persisted state before reporting.

**Measured failure this prevents.** A sweep of every disconnect-finalised session in production history (11 sessions, 6 chargers) found **3 reboot-resets**. Chronologically perfect replay, arithmetically wrong bill:

```
meterStart  11,000 Wh
            14,200 Wh
            ── power cut · register resets ──
               900 Wh   ← meterStop
energy = 0.9 − 11.0 = −10.1 kWh
```

**What we do about a violation:** nothing corrective. The charger is the instrument of record; we store and bill exactly what is reported, and raise an alert (`transaction.meter_regression`). With `PostBootState` retired there is no server-side recovery and no credit note to fix an invoice, so this alert is the only way we will learn that persistence has failed in the field. Please treat one as a firmware defect report.

## R4 — Torn-write durability for persisted transaction state (new)

Persist, together: `transactionId`, `meterStart`, the last cumulative reading, and the accepted `maxEnergy`. Rotate the write across live-state slots, checksum each record, and on boot take the newest slot that validates.

**Failure it prevents:** a power cut landing mid-write — the exact event the value exists to outlive. A half-written record that validates as zero reproduces the R3 failure with no signal.

**Why this carries more weight than it looks:** retiring `PostBootState` makes charger-side persistence the **sole** remaining meter-recovery path. There is no fallback behind it.

## R5 — Metering state is protected from diagnostic buffering (agreed, and small)

The Diagnostic Bundle ring may wrap; that is fine for disposable observability data and unacceptable for billing data. Diagnostics must never be able to overwrite metering state.

The requirement is smaller than it was first sized. Billing needs only the cumulative odometer (`end − start`), so what must survive is: `meterStart`, the last reading, `maxEnergy`, and the `StopTransaction` — a few hundred bytes. Losing intermediate `MeterValues` frames to a wrap costs granularity, not energy. Frame density above that floor is an audit and live-display choice you may trade freely against diagnostic depth.

## R6 — Name the retry cadence by the standard keys (minor)

The HLD hardcodes "3 attempts, then 3 every 30 min". Keep whatever values you choose, **fleet-wide**, but expose them under the standard OCPP 1.6 names `TransactionMessageAttempts` and `TransactionMessageRetryInterval` so the behaviour is legible to any OCPP tooling. We will not set them per charger: **the CSMS does not send `ChangeConfiguration`, and all charger behaviour is fleet-wide in firmware** (decided 2026-09-15).

## R7 — No local start path without telling us (informational)

Today a session can only begin with `RemoteStartTransaction` from the CSMS, which an offline charger cannot receive. That, and nothing else, is what makes offline *start* impossible — we deliberately do not assert `AllowOfflineTxForUnknownId` / `LocalAuthorizeOffline`. If a future firmware adds any local start path (RFID reader, plug-and-charge, a start button), it must ship with both keys held `false` and you must tell us, so we can build the server-side assertion at the same time.

## What changes on our side

All of this is built and tested; none of it needs anything from firmware to be safe today.

- **Late `StopTransaction` records the truth without moving the money** (migration 64). A stop for a session we already closed lands in reported-only fields; the billed figures and the issued GST invoice are untouched. Replayed `MeterValues` for a closed session are stored, acknowledged, and never billed.
- **The suspend window measures silence.** A session is held open as long as we keep hearing about it; the clock resets on every reading. 48 h latched / 12 h unlatched.
- **`SessionLimit` is pushed** after `StartTransaction.conf`, on every WebSocket connect for every open transaction, and whenever a budget changes. Every reply outcome is counted. **`StopDetail` is accepted** and recorded beside the OCPP stop reason.
- **Monotonicity is observed, never corrected** (R3).
- **`PostBootState` and `GetLastMeterValue` are retired only after** every connected charger runs firmware satisfying R3 + R4. We will ask you for the version number that does, and audit the fleet against it before removing either message.

## Questions we need answered

1. **R2 keying:** can the limit be keyed on `transactionId` rather than `idTag`? If not, what is the constraint?
2. **R3/R4 mechanism:** how is the cumulative reading reconstructed after a register reset, and how often is the persisted record written (per frame? per N Wh?)? We need the write cadence to reason about the worst-case under-report after a power cut.
3. **Which firmware version** will be the first to satisfy R1–R5 together? That version number is the gate for retiring `PostBootState`.
4. **Timestamp source while offline:** is the RTC held across a power cut, or does it come up at epoch until NTP? (Determines how many replayed frames will carry a usable measured time.)
5. **Queue depth:** how many transaction-related messages can be queued before the oldest is dropped, and is `StopTransaction` protected from eviction?

## Checklist for the review

- [ ] R1 accepted: contactor held on WS loss; safety paths unchanged; transaction messages queued and replayed in order
- [ ] R2 accepted or countered: `transactionId` keying; `Rejected` on mismatch; open the contactor if no limit was accepted before link loss
- [ ] R3 accepted or countered: wire-level invariant, reconstruct before reporting
- [ ] R4 accepted: slot rotation, checksums, newest-valid-on-boot
- [ ] R5 accepted: metering state isolated from diagnostic ring
- [ ] R6 accepted: standard key names, fleet-wide values
- [ ] R7 acknowledged
- [ ] New firmware confirmed to Accept-and-ignore `PostBootState` (never apply the pushed meter value)
- [ ] Continuity and the cap confirmed to ship in **one** release
- [ ] Gate firmware version for `PostBootState` retirement named
- [ ] Any counter-proposal that changes what the CSMS sends is fed back into ADR 0031, not absorbed silently
