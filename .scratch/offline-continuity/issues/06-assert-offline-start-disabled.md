# Assert offline session start stays disabled

Status: wontfix

## What to build

[[offline-charging-continuity]] is about *surviving* an outage mid-session; it must never allow one to *begin* during an outage. Every **Charging Session** requires a funding decision only the CSMS can make — a QR payment webhook or a wallet balance — so a charger authorized to start offline is a charger that can deliver energy nobody has paid for, with no `Transaction` row to bill against.

OCPP 1.6 permits offline starts through standard configuration keys. Set them explicitly rather than trusting the vendor default, and verify rather than assume: read the keys back on connect, record what the charger actually reports, and raise a visible signal when a charger is configured to allow offline starts.

Treat this as a per-charger property surfaced to operators, not a silent correction — a charger answering the wrong way is a provisioning fault worth seeing.

See ADR 0031 decision 9.

## Acceptance criteria

- [ ] The relevant offline-authorization keys are set to disabled explicitly, not left at vendor default
- [ ] The keys are read back and the charger's actual values recorded
- [ ] A charger reporting offline-start as enabled produces an alertable event and is visible to operators
- [ ] A charger that does not support the keys at all is recorded as such and does not error the connection
- [ ] The assertion is part of commissioning, not only a one-off script

## Blocked by

None - can start immediately

## Descoped 2026-09-15 — build only if firmware gains a local start path

Both keys are unreachable in this fleet. They govern what a charger does when an id tag is presented *to the charger* (RFID tap, button) while offline. No charger has such a path: the CSMS does not implement the `Authorize` handler at all, every session begins with a `RemoteStartTransaction` after a funding decision, and an offline charger cannot receive one. Offline start is impossible by construction. Building the assertion would have added the first outbound `ChangeConfiguration`/`GetConfiguration` exchange in the codebase, a migration and a UI row to guard a path that does not exist.

Broader decision recorded the same day: **the CSMS does not set per-charger configuration; charger behaviour is fleet-wide in firmware.**

**Trigger to reopen:** firmware adds any local start path (RFID reader, plug-and-charge, start button). The firmware spec (`docs/firmware/session-limit-spec.md`) requires such a path to ship with both keys `false` and to be announced.

**Plan preserved for that day:** run in `after_boot_notification` after the PostBootState push; `ChangeConfiguration` both keys to `false`, then one `GetConfiguration` for both; record to `Charger.offline_start_allowed` (tri-state: true = fault, false = confirmed, null = unknown/unsupported) + `Charger.offline_start_config` (raw read-back, statuses, checked_at); `unknownKey` / `NotSupported` = unsupported, not a fault; a `true` read-back logs at error, audits `charger.offline_start_enabled`, emits `Custom/OCPP/OfflineStart/Enabled` + NR event; charger detail page shows an "Offline start" row (Disabled / Enabled — provisioning fault / Unknown, IST check time); tests for each outcome.
