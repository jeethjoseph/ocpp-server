# Firmware-side defects to raise with the firmware team

Status: wontfix

## What to build

Nothing in this repo. This issue exists so the firmware-side defects found on 2026-08-27 are tracked somewhere rather than living only in an ADR's context section. The redesign removes our *dependence* on most of them; it does not fix them, and two are still doing damage.

**Still live, worth fixing regardless of the redesign:**

1. **§2.2 metering data in traces.** The server redactor is stripping ~28 cumulative-energy values per bundle (`Meter E: 0.00000 kWh`). Firmware-side redaction is under-matching — it reported `redacted: 0 meter` while the values were plainly in the body. Server-side redaction is a second line of defence, not a licence to emit. This is the one with compliance weight: a second unaudited copy of billing-relevant energy is a liability, not an asset.

2. **The charger logs our HTTP response into its own ring buffer.** Issue 01 shrinks the response, which fixes our half. Firmware should not be writing response bodies into the log buffer at all — it consumes the resource the buffer exists to preserve, and it recurses.

**Moot after the redesign, but worth them understanding as bugs:**

3. **`overflow` emitted with inconsistent sign** — values decode as `-1`, `-191`, `-18100`, `-19148` in two's complement, with magnitudes matching `first_record - 1` exactly. A signed subtraction stored into an unsigned field.

4. **`seq` not incremented between distinct bundles** — four consecutive bundles covering four different record windows all carried `seq=4`, against spec §4.1.

5. **`boot` skipping values and resetting** — ran `54, 56, 58`, then `1`.

Items 3-5 all disappear when the header does, but they are the same class of defect (counters that do not survive contact with reboot), so they may indicate problems elsewhere in the firmware that the header merely made visible.

## Acceptance criteria

- [ ] Items 1 and 2 raised with the firmware team with the evidence attached, and tracked wherever their work is tracked.
- [ ] Items 3-5 communicated as context so the header removal is understood as a response to a real constraint rather than a unilateral API change.
- [ ] Confirm the firmware team's actual persistence constraint in writing: no persisted *counters* (buffer and write head survive reboot), or no persistence at all beyond raw buffer contents. ADR 0030 assumes the former; the latter needs record-level dedupe rather than bundle-level.

## Blocked by

- None

## Comments

**2026-08-27 — closed, not actioned.** User's call: do not chase the firmware team on any of these.

Items 3-5 (the counter bugs) are genuinely moot — the header they lived in is gone.

Two are being dropped while still live, recorded here so the decision is visible rather than lost:

- **Item 1, metering data in traces.** Still arriving (157 cumulative-energy values in a 196 KB bundle). Our server-side redaction strips it before anything reaches S3, so nothing sensitive is stored — but it is leaving the charger, and the reason spec §2.2 forbids it is compliance, not tidiness: a second unaudited copy of billing-relevant energy alongside the audited `MeterValues` path. The mitigation holds; the exposure is on the wire, not at rest.
- **Item 2, charger logs our HTTP response.** Half-fixed regardless — issue 01 cut the response to ~120 bytes, so the amplification is now small.

**Q1 answered by the user (2026-08-27): option (b).** The charger persists only its identity and configuration — charger ID, server endpoint, auth key. No counters, no markers, no pointers. See ADR 0030, which assumed (a).
