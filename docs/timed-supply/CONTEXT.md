# Timed Supply Control System (working name)

A greenfield product, architecturally modelled on the VoltLync EV-CSMS but for a
**generic on/off supply billed by time, not energy**. A customer finds a
**Machine** on a map (or scans its QR), starts it from the app, the Machine
delivers an abstract **safe low-voltage supply** while switched on, and is billed
for the **seconds the supply was on**. Unattended; pure-time (no flow sensor).

This is **not** the EV product and does **not** reuse its code — the EV CSMS is the
_reference architecture_ only. Terminology below is deliberately distinct from the
EV glossary (`../../CONTEXT.md`) to prevent conflation.

## Language

**Machine**:
The customer-facing unit that delivers the supply, identified by a stable device
id. Analogue of the EV **Charger/EVSE**, but a **Machine** has no energy meter — it
is a relay plus a connection watchdog. Customer-facing label (per the concept
wireframe: "search for machine", "picture of machine"). _Avoid_: "charger",
"EVSE" (energy-metered connotation), "device" as a customer-facing word.

**Supply**:
The abstract resource switched on/off behind the Machine's relay. **Safe
low-voltage** (inherently safe to switch and to restart unattended). _Avoid_:
"energy", "charge", "power" (imply metering that does not exist here).

**Supply Session** / **Session**:
One billable episode from Start to Stop, billed by **connected-on seconds**. A
Session may span **multiple connected-on intervals** with off-gaps between them
(see **Connectivity-gated supply** + **Resume window**). Analogue of the EV
**Charging Session**, but the billable quantity is time, not kWh. _Avoid_:
"transaction" as the customer-facing word; "charging session".

**Connected-on time** / **Billable seconds**:
The billable quantity: the sum of wall-clock seconds during which the Session was
**both switched on and the Machine was connected to the server**. Measured
**server-side**; there is no device-side counter. This is the metering primitive
that replaces the EV system's device-reported kWh. _Avoid_: "duration" unqualified
(the calendar span start→stop includes unbilled off-gaps and is a different
number).

**Connectivity-gated supply** (the core invariant):
_Supply flows only while the Machine is connected to the server._ On loss of the
server link the Machine's watchdog opens the relay (supply OFF); on reconnect
within the **Resume window** the supply auto-restarts (safe because the supply is
low-voltage and unattended). Consequences: no unbilled/unbounded offline supply,
the stop/budget command can always reach an actively-supplying Machine, and not
billing an off-gap is _exact_ (nothing flowed), not an approximation. See
[[adr-0001-connectivity-gated-server-metered-supply]]. _Avoid_: assuming supply can
be on while disconnected.

**Resume window**:
The 30-minute grace after a disconnect during which a suspended Session may
resume (accumulating more connected-on time) rather than being finalized.
Analogue of the EV resume-staleness threshold (ADR 0022), but here it must sit
_well above_ the heartbeat interval so the ordering can never invert (the bug that
force-finalized live EV resumes). _Avoid_: "timeout" unqualified.

**Max-on cap** / **Budget-derived cap**:
The server-enforced upper bound on a prepaid Session's connected-on seconds:
`max_on_seconds = spendable_budget / rate_per_second`. Enforced server-side by
issuing a stop when elapsed connected-on time crosses it — always deliverable
because an actively-supplying Machine is, by the invariant, connected. Analogue of
the EV **Budget cap**, denominated in seconds instead of kWh.

**Zero-supply blindness** (a known, accepted limitation):
Because billing is **pure-time with no sensor**, the system _cannot detect_ that
the supply behind the relay was dead — it bills for on-time regardless of whether
anything actually flowed. The EV system's "zero-energy → full refund" path has
**no analogue here** and cannot be built without adding a sensor. A decision the
client must explicitly accept. See [[adr-0001-connectivity-gated-server-metered-supply]].
_Avoid_: promising any "nothing-flowed refund".

## Relationships

- A **Supply Session** is metered by the server as accumulated **Connected-on
  time**; there is no device meter.
- **Connectivity-gated supply** makes the off-gap between two connected-on
  intervals unbillable _by construction_ (supply was physically off).
- The **Max-on cap** is always enforceable because supply implies connectivity.
