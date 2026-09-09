# Diagnostic Bundle: remove the header

Implements [ADR 0030](../../docs/adr/0030-diagnostic-bundle-body-is-the-contract.md).

**Unchanged:** HTTPS transport, Charger Auth Key Basic Auth (ADR 0020), S3 archive, durability gate, redaction, rate limiting, cadence, OTLP fan-out.

**Changing:** the bundle header is deleted. Identity moves to a content hash; reboot and time come from in-band records the firmware already emits; loss accounting moves to a UTC window (or is dropped — see the scope question below).

## Scope decision (settled)

**2026-08-27: loss accounting stays.** Issue 04 is built. It is understood to be approximate — minutes not records, no cumulative overwrite count, and dependent on a network-sourced clock anchor. A coarse signal beats none, since silent loss was the original justification for the feature.

## Order

| # | Issue | Status | Blocked by |
|---|---|---|---|
| 01 | Trim upload response | **done** | — |
| 02 | Shared in-band marker parser | **done** | — |
| 03 | Content-hash identity | **done** (mig 53) | — |
| 04 | UTC loss window | **done** (mig 54) | 02 |
| 05 | Remove header, stop writing columns | **done** (mig 55) | 03, 04 |
| 06 | Atomic archive + index | **done** (mig 56) | — |
| 07 | Purge diagnostics archive | **done** | — |
| 08 | Firmware spec v2 + domain docs | **done** | 05 |
| 09 | Drop superseded columns | **blocked** — no traffic to soak against | 05 + soak |
| 10 | Firmware-side defects | **wontfix** (user's call) | — |

## Outage: resolved

The staging 500 loop stopped on its own before issue 05 shipped (last upload 10:12 UTC 2026-08-27). Issue 05 removes the cause regardless — there is no longer a header field to overflow an int32 column.

The archive it stranded was purged entirely on 2026-08-27 (issue 07): 211 objects and 16 rows deleted, bucket and table now empty. Next real upload starts clean.
