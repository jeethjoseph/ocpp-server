# Firmware requirements for offline continuity, agreed with the firmware team

Status: ready-for-human

## What to build

A firmware specification the firmware team accepts, covering [[offline-charging-continuity]] and the four places our design differs from their HLD. This is a negotiation, not a document drop — each item exists because the alternative fails in a specific way.

**Continuity itself.** Connectivity loss alone never opens the contactor and never triggers a reset. Local safety supervision — earth fault, leakage, over/under voltage, over-current — is untouched and still stops the charge through its existing paths. The only thing suppressed is a reset whose sole cause is that the CSMS is unreachable.

**Retry cadence uses the standard OCPP configuration keys**, not a firmware-hardcoded schedule. Same behaviour, but tunable per charger from the CSMS without a flash, and legible to any OCPP tooling.

**`SessionLimit` is keyed on `transactionId`, not `idTag`.** The id tag is per-`User` and reused across every session that customer ever has, so it cannot identify a session; the ambiguity is worse against a limit held in EEPROM across reboots.

**The stored last-energy value needs torn-write durability.** Rotate the write across slots, checksum each record, and on boot take the newest that validates. The failure mode is a power cut landing mid-write — the exact event the value exists to outlive. This carries more weight than it appears to: retiring `PostBootState` leaves charger-side persistence as the **sole** remaining meter-recovery path.

**The meter invariant is about the wire, not the hardware.** An involuntary register reset cannot be scheduled away — a power cut resets the meter and drops the link together. The achievable requirement is: *never report a cumulative reading lower than one already reported for this transaction.* The register may reset; the firmware must reconstruct before reporting.

**Metering state is protected from diagnostic buffering — and it is small.** Diagnostics must never overwrite metering state. But billing needs only the cumulative odometer, the last reading and the stop, so the requirement is "make sure those survive and diagnostics cannot scribble on them", not "carve up the EEPROM". Frame density above that floor is an audit choice, freely traded against diagnostic depth.

See ADR 0031 decisions 1, 2, 7 and 10.

## Acceptance criteria

- [ ] Spec written and reviewed with the firmware team, with each requirement's failure mode stated
- [ ] Firmware team has explicitly accepted or countered the `transactionId` keying, the standard retry keys, torn-write durability, and the wire-level meter invariant
- [ ] The `SessionLimit` payload shape is agreed and matches what the CSMS sends
- [ ] Any counter-proposal that changes CSMS behaviour is fed back into ADR 0031 rather than absorbed silently
- [ ] Continuity and the local energy cap are agreed to ship together, never independently

## Blocked by

None - can start immediately
