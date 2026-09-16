# Firmware requirements for offline continuity, agreed with the firmware team

Status: ready-for-human — spec written, review to book

## What to build

A firmware specification the firmware team accepts, covering [[offline-charging-continuity]] and the four places our design differs from their HLD. This is a negotiation, not a document drop — each item exists because the alternative fails in a specific way.

**Continuity itself.** Connectivity loss alone never opens the contactor and never triggers a reset. Local safety supervision — earth fault, leakage, over/under voltage, over-current — is untouched and still stops the charge through its existing paths. The only thing suppressed is a reset whose sole cause is that the CSMS is unreachable.

**Retry cadence is named by the standard OCPP configuration keys** (`TransactionMessageAttempts` / `TransactionMessageRetryInterval`) rather than an unnamed hardcoded schedule, so it is legible to any OCPP tooling. The values stay **fleet-wide in firmware** — decided 2026-09-15: the CSMS does not set per-charger configuration and has no configuration surface. This is now a naming request, not a behaviour change.

**Any future local start path (RFID reader, plug-and-charge, start button) must ship with `AllowOfflineTxForUnknownId` and `LocalAuthorizeOffline` held `false`, and must be announced to the CSMS team** — today offline start is impossible by construction (no `Authorize` handler, sessions begin only by `RemoteStartTransaction`), and issue 06's assertion is built only when that changes.

**`SessionLimit` is keyed on `transactionId`, not `idTag`.** The id tag is per-`User` and reused across every session that customer ever has, so it cannot identify a session; the ambiguity is worse against a limit held in EEPROM across reboots.

**The stored last-energy value needs torn-write durability.** Rotate the write across slots, checksum each record, and on boot take the newest that validates. The failure mode is a power cut landing mid-write — the exact event the value exists to outlive. This carries more weight than it appears to: retiring `PostBootState` leaves charger-side persistence as the **sole** remaining meter-recovery path.

**The meter invariant is about the wire, not the hardware.** An involuntary register reset cannot be scheduled away — a power cut resets the meter and drops the link together. The achievable requirement is: *never report a cumulative reading lower than one already reported for this transaction.* The register may reset; the firmware must reconstruct before reporting.

**Metering state is protected from diagnostic buffering — and it is small.** Diagnostics must never overwrite metering state. But billing needs only the cumulative odometer, the last reading and the stop, so the requirement is "make sure those survive and diagnostics cannot scribble on them", not "carve up the EEPROM". Frame density above that floor is an audit choice, freely traded against diagnostic depth.

See ADR 0031 decisions 1, 2, 7 and 10. **The `SessionLimit` / `StopDetail` wire contract is written and matches what the CSMS sends: `docs/firmware/session-limit-spec.md` (2026-09-15).** Its rule 5 — a transaction with no accepted limit opens the contactor on link loss — is a new item for the firmware team to accept or counter.

## Acceptance criteria

- [ ] Spec written and reviewed with the firmware team, with each requirement's failure mode stated
- [ ] Firmware team has explicitly accepted or countered the `transactionId` keying, the standard retry-key naming, torn-write durability, the wire-level meter invariant, and the no-local-start-path rule
- [ ] The `SessionLimit` payload shape is agreed and matches what the CSMS sends
- [ ] Any counter-proposal that changes CSMS behaviour is fed back into ADR 0031 rather than absorbed silently
- [ ] Continuity and the local energy cap are agreed to ship together, never independently

## Blocked by

None - can start immediately

## 2026-09-15 — spec written

`docs/firmware/offline-continuity-required-changes-v1.0.md` (house style of the diagnostic-bundle required-changes docs): seven requirements R1–R7, each with the failure it prevents and its status against the HLD (R2, R3 change; R4 new; R6 minor; R7 informational), what the CSMS already does, five questions the review must answer (keying, reconstruction mechanism + write cadence, gate firmware version, RTC behaviour, queue depth / StopTransaction eviction), and the review checklist. Wire detail for the cap lives in `session-limit-spec.md`. Remaining work on this issue is the meeting itself and feeding any counter-proposal back into ADR 0031.
