# CSMS pushes and maintains SessionLimit

Status: ready-for-agent

## What to build

Push the **Budget cap** to the charger so it can be enforced locally, which is what makes [[offline-charging-continuity]] safe: a charger that keeps delivering while unreachable and has no local energy limit delivers unbounded free energy.

Send it as a vendor `DataTransfer` with `messageId=SessionLimit`, carrying an **absolute Wh value**, immediately after the CSMS has assigned a transaction id. OCPP 1.6 has no native per-transaction energy limit — smart charging constrains power over a schedule, not cumulative energy — so a vendor extension is the idiomatic answer here.

Four rules that are load-bearing:

- **Keyed on `transactionId`, never `idTag`.** The id tag is a per-`User` value reused across every session that customer ever has, so it cannot identify a session — and the ambiguity is worse against a limit the charger persists across reboots.
- **Round the Wh conversion down.** Rounding up makes over-delivery past what the customer paid structural rather than bounded by RemoteStop latency.
- **Absolute value, idempotent, re-sendable.** Re-assert the current limit on every reconnect, and re-push whenever the budget changes.
- **The charger is the source of truth; the server-side budget check stays as a redundant failsafe.** Whichever enforcer fires first wins — the existing flag-less at-least-once pattern, extended across the link.

Shape the payload fields as `maxEnergy` / `maxCost` / `maxTime` even though only the first is populated, mirroring the native construct that lands in OCPP 2.1, so a later migration is a transport swap rather than a redesign.

Verifiable end-to-end against the charger simulator without firmware existing. Per project convention, ship the simulator support and the firmware-facing message spec alongside the backend change.

See ADR 0031 decision 2 and the **Budget cap** entry in CONTEXT.md.

## Acceptance criteria

- [ ] `SessionLimit` is sent once the transaction id exists, carrying an absolute Wh value keyed on `transactionId`
- [ ] The Wh conversion rounds down; a test pins the direction
- [ ] The current limit is re-asserted on reconnect
- [ ] A budget change re-pushes the new absolute value; sending the same value twice is harmless
- [ ] Internal-role sessions receive no limit (no budget cap applies, per ADR 0004)
- [ ] The charger's response — accepted, rejected, unanswered — is logged and counted, and a rejection does not fail the session
- [ ] The server-side budget check still fires independently
- [ ] Simulator handles the message; firmware-facing spec written

## Blocked by

None - can start immediately
