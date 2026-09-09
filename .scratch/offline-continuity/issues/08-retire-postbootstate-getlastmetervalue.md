# Retire PostBootState and GetLastMeterValue

Status: ready-for-human

## What to build

Remove both halves of the meter-recovery handshake. They exist only because the charger could not remember its own meter; once firmware persists it, the CSMS telling a metering device what its own meter reads is backwards.

`PostBootState` pushes our meter baseline to the charger on boot. Under [[offline-charging-continuity]] the charger holds better data than we do — and our value is worse than it looks, because after a write-off the figure we would push is exactly the stale one. `GetLastMeterValue` is the pull-shaped twin of the same obsolete idea.

**The gate is a fleet condition, not a code condition, which is why this is not an AFK task.** Current firmware depends on the `PostBootState` push to restore its register after a reboot; deleting it before the fleet is upgraded reintroduces the `meterStart = 0` class of bug on exactly the units that cannot defend themselves — the mechanism that turned a phantom 158 kWh into a full-value charge on production transaction 1377.

One side effect must survive the removal: `GetLastMeterValue` is currently one of the paths that resumes a suspended session. That resume has to be guaranteed by the MeterValues path, which already auto-resumes.

See ADR 0031 decision 6.

## Acceptance criteria

- [ ] Fleet firmware audit confirms every connected charger persists its own meter state; the check is recorded, not assumed
- [ ] Session resume is verified through the MeterValues path with both messages absent
- [ ] Both handlers and the push path are removed, along with the now-unused last-meter lookup that fed the push
- [ ] No charger in either environment is left relying on a message that no longer exists
- [ ] ADR 0031 updated to record the date the gate was satisfied

## Blocked by

- `07-firmware-requirements-handoff.md`
