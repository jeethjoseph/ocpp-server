# Assert offline session start stays disabled

Status: ready-for-agent

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
