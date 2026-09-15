# Modem AT chatter is overwriting in-flight OCPP frames

Status: ready-for-human

## ELI5

The charger was halfway through telling us "connector 1 is Available, at time…" when the
modem's own command console started writing into the same pipe. The sentence never finished.
What arrived was half an OCPP message with modem commands stapled onto the end.

The server couldn't parse it, so the record of that message was dropped. The charger has no
idea — it believes it sent a status update.

## Evidence

The clearest sample, from the OCPP message logger:

```
[2, "status_2F4302C4", "StatusNotification", {"connectorId":1,"errorCode":"NoError",
 "status":"Available","timestamp":"2026-08-10AT+QWSCLOSE=0\r\nAT+CPIN?\r\nAT+CPIN?\r\n
 AT+CPIN?\r\nAT+QWSCLOSE=0\r\n
```

Read it carefully. The frame is valid JSON right up to `"timestamp":"2026-08-10` — then it is
**cut mid-value** and AT-command traffic is spliced in where the rest of the ISO timestamp
should be. The frame never closes.

The AT commands are not random. `AT+QWSCLOSE=0` is the **WebSocket close** command, and
`AT+CPIN?` is the SIM check that begins the modem's reconnect sequence. So the corruption
happens precisely as the firmware tears the socket down and restarts the modem: the AT
console and the WebSocket payload appear to share a buffer, and the teardown chatter
overwrites a frame still being transmitted.

Other samples are pure AT with no OCPP prefix at all:

```
Value "AT\r\nATE0\r\nAT+CPIN?\r\nAT+CREG?\r\nAT+CREG?\r\nAT+CR is invalid json value.
```

`ATE0` is echo-off, the first line of modem init — the whole boot sequence went out over the
WebSocket as if it were an OCPP message.

## Scope, honestly

**5 occurrences in 90 days, all on staging, zero on production.** So this is rare and, on
current evidence, confined to whatever firmware staging units are running.

**It is not established that this caused the 2026-09-07 fleet outage.** The dates
(2026-08-10, 08-13, and three on 09-03) do not line up, and a query for disconnect events
around the 09-03 burst returned nothing. The resemblance to that incident is that both involve
`AT+QWSCLOSE` and the modem's socket handling — which is suggestive of a shared area of
firmware, not evidence of a shared cause. See [[project-fleet-tls-outage-2026-09-07]], which
remains unexplained.

## Why it is worth fixing anyway

The visible cost is small — a dropped row in the OCPP message log, which is observability
rather than billing. Nothing in the audited energy path depends on it.

The invisible cost is the concern. This is a charger emitting bytes it did not intend to
emit, on the channel that carries transaction control. A `StatusNotification` was destroyed
here; the same mechanism could truncate a `StopTransaction` or a `MeterValues`. The server
rejects malformed frames, so the failure mode is a **lost** message rather than a
misinterpreted one — but a lost StopTransaction is a session that does not close.

It also means the charger's own diagnostic trace and its OCPP uplink are not properly
isolated from each other, which is the sort of thing worth knowing before it matters.

## What to do

Firmware-side, not server-side. There is no server fix: the frames are already corrupt on
arrival, and rejecting them is correct.

- Confirm whether the AT command channel and the WebSocket TX buffer are genuinely shared on
  the affected firmware, or whether this is a race during `AT+QWSCLOSE` teardown specifically.
- Establish which firmware versions are affected. All samples are staging; the production
  fleet spans 1.7.1–2.0.1 and shows none, which may mean the defect is fixed, not present, or
  merely not yet observed.
- Worth raising alongside the §4.3 in-band record contract in the firmware spec (v2.0), since
  both concern what the charger is permitted to put on the wire.

## Acceptance criteria

- [ ] Root cause identified firmware-side: shared buffer vs. teardown race.
- [ ] Affected firmware versions established, and whether production units are exposed.
- [ ] A regression check that a socket teardown mid-frame cannot emit AT text on the OCPP channel.

## Comments

**2026-09-08 — found while checking whether a background-task bug had ever fired in
production.** It had not, but querying `Log` for background-task failures surfaced these
alongside 7 genuinely lost audit writes. See
[[.scratch/background-task-db-context/issues/01-detach-fire-and-forget-db-context]].

These are only visible because `log_message` failures are logged; the corrupt frames
themselves are rejected before that. There may be more that fail earlier and leave no trace.
