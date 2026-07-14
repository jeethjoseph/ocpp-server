# Supply is connectivity-gated and metered server-side by wall-clock time

For the Timed Supply product we bill by **seconds the supply is on**, not by a
device-reported meter. We decided the **Machine may deliver supply only while it is
connected to the server** (its watchdog opens the relay on link loss), and the
**server** measures billable time on its own wall-clock as accumulated
**connected-on seconds**. There is no device-side counter and no flow sensor.

## Context — time has no meter, and that changes everything

The reference EV-CSMS bills `energy_consumed_kwh × rate`, where energy is a
**monotonic counter reported by the device** via OCPP `MeterValues`. That single
property silently underwrites three behaviours: the budget cap self-heals (a lost
`RemoteStop` just re-fires next frame, energy only goes up), "zero-energy → full
refund" is _measurable_ (the meter proves nothing flowed), and the system never
bills for supply it did not deliver (the meter, not the clock, is truth).

Billing by **time** comes with **no meter**. So the source of truth for billable
seconds is a genuine fork with three shapes:

- **A — Server wall-clock.** `stop − start` measured server-side; device is a dumb
  relay. Simple, but a device that drops offline while physically ON is invisible
  to the server: keep the clock running (**overbill** across a dead link) or freeze
  it (**underbill**), and — worse — the server's only lever (`stop`) cannot reach an
  offline relay, so a wedged unit delivers **unbilled, unbounded supply** with
  nothing able to stop it. A safety hole, not just a billing one.
- **B — Device-reported on-duration.** The device counts its own on-time like a
  meter. Restores self-healing, but requires an RTC/counter and reporting protocol
  on the device.
- **C — Hybrid.** Server pushes a budget-derived max-on to the device; device
  self-enforces it and reports actual on-time on reconnect. Most robust, most work
  on both sides.

## Decision

Take a **fourth path that makes A safe by construction**: gate the supply on
connectivity.

- The **Machine** is a relay + a **connection watchdog**. On loss of the server
  link the watchdog **opens the relay** (supply OFF). No device counter, no RTC, no
  device-side metering — the simplest possible firmware.
- The **server** meters billable time on its wall-clock, accumulating only
  **connected-on seconds** (elapsed while the Session is on _and_ the Machine is
  connected).
- The load-bearing invariant: **supply flows only while connected.**

Everything good follows from that one invariant:

1. **No unbilled/unbounded offline supply.** A dead link means the supply is
   _physically off_. The safety hole in path A is closed without a device-side
   fail-safe timer.
2. **The stop / budget cap is always enforceable.** An actively-supplying Machine
   is, by definition, connected, so a stop command can always reach it while it
   matters. (In the EV system a stop could be lost to an offline charger; here it
   cannot, _while supply is flowing_.)
3. **Not billing an off-gap is exact, not a concession.** Supply genuinely did not
   flow during a disconnect, so excluding that time is correct — the underbill
   worry of path A/A2 evaporates.
4. **Sessions span multiple connected-on intervals.** On reconnect within the
   **Resume window** (30 min, chosen ≫ heartbeat so the ordering cannot invert the
   way it did on the EV fleet), the supply **auto-restarts** and the Session
   accumulates more connected-on time. Auto-restart is acceptable **only because
   the supply is safe low-voltage and the deployment is unattended** — for a
   hazardous or attended supply this decision would flip to require an explicit
   human Start.

## Accepted limitation — zero-supply blindness

Because metering is **pure-time with no sensor**, the system **cannot detect** that
the resource behind the relay was dead. It bills for connected-on time whether or
not anything actually flowed. The EV "zero-energy → full refund" path has **no
analogue** and cannot exist without adding a sensor. This is a **product decision
the client must explicitly accept**: the customer pays for on-time even if the
supplied thing was broken. Revisiting it means adding a flow/energy sensor and a
reconciliation path — a different (B/C-shaped) architecture.

## Considered alternatives

- **A — pure server wall-clock, dumb relay (no connectivity gate).** Rejected: the
  offline-while-on case forces an overbill/underbill choice _and_ leaves an
  uncontrollable, unbilled, potentially unsafe supply during a dead link. The
  connectivity gate is what rescues A.
- **B — device-reported on-duration.** Rejected for v1: pushes an RTC, a counter,
  and a reporting protocol onto the device for a benefit (billing across
  deliberate offline operation) this product does not need, since we _want_ supply
  off when disconnected anyway.
- **C — server-pushed max-on + device self-enforcement + reported on-time.** Was
  briefly adopted mid-design then reverted: it is the right answer _only if_ supply
  must continue across disconnects. Given the unattended, safe-low-voltage,
  supply-off-when-disconnected posture, the connectivity gate delivers the same
  safety with dumber, cheaper firmware.

## Consequences

- **The server needs an active per-Session clock**, unlike the EV system whose
  budget checks are purely reactive to inbound `MeterValues` frames. Something must
  drive elapsed-time evaluation and the max-on cap on a timer (a server-side ticker
  or a heartbeat-driven check); the exact mechanism is an open build decision.
- **Heartbeat is the metering signal.** Billable time is bounded by the last
  proof-of-life, so heartbeat interval sets both metering granularity and how fast
  a disconnect is noticed. The Resume window (30 min) must stay well above it; a
  startup invariant check should assert `resume_window ≫ heartbeat` so the EV
  ordering bug cannot recur.
- **Flaky links cause supply flap** (off on drop, auto-on on reconnect). Harmless
  for safe low-voltage; would need debounce/interlock for anything with mechanical
  inrush — another reason this ADR is scoped to the safe-low-voltage envelope.
- **The firmware is delivered by a separate team** against our frozen device WS
  protocol: relay + connection watchdog with a bounded open-on-link-loss timeout,
  heartbeat, and remote start/stop. No metering firmware required. The protocol is
  the interface contract; the watchdog behaviour is the one non-negotiable clause.
