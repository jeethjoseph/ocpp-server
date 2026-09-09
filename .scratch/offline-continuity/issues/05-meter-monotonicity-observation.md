# Observe meter monotonicity violations

Status: ready-for-agent

## What to build

Detect and report when a charger reports a cumulative meter reading **lower than one it has already reported for the same transaction**, without correcting it.

The charger owns the meter and it is the instrument of record: bill exactly what is reported, clamp nothing. But record the violation as an alertable event, because with `PostBootState` retired there is no meter-recovery fallback and no credit note to correct an invoice issued on a bad figure. This is the only signal that charger-side meter persistence has failed in the field.

The failure this catches is real and measured: the ADR 0022 fleet sweep found **3 of 11 sessions showed a reboot-reset**, where the register returned to zero after a power cut. A site power cut resets the register and drops the link in the same event, which is precisely the scenario [[offline-charging-continuity]] exists to survive. The firmware is required to reconstruct the true cumulative value before reporting — see the **Meter reporting invariant** in CONTEXT.md — and this is how we find out whether it does.

See ADR 0031 decision 7.

## Acceptance criteria

- [ ] A reading below a previously reported reading for the same transaction emits an alertable custom event and an audit entry
- [ ] The reading is still stored and still bills as reported — no clamping, no rejection, no session interruption
- [ ] The event carries enough to diagnose: transaction, charger, previous and current readings, and the delta
- [ ] The check is cheap enough to sit on the MeterValues path without adding a query per frame
- [ ] A session whose readings only ever advance emits nothing

## Blocked by

None - can start immediately
