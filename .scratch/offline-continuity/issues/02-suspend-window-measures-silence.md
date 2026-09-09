# The suspend window measures silence, not session age

Status: ready-for-agent

## What to build

Change what the **Suspend window** clock measures. It currently counts from `suspended_at` — effectively session age once suspended — so a session is force-finalized at the window even if the charger has been checking in throughout. Under [[offline-charging-continuity]] that kills sessions we can see are alive.

Measure instead the time since we last heard **anything about that transaction**. Every check-in resets it. The window then governs only the no-information case, which is what it was always meant to answer.

Consequence to accept deliberately: there is no upper bound on session duration while a charger keeps reporting. That is correct — advancing energy is proof of life, and the money is bounded by the **Budget cap** regardless.

Keep the current magnitudes in this slice. Raising them is a separate decision (see the blocked-by note on the magnitudes issue) so the mechanism does not wait on an undecided number. This slice is therefore behaviour-preserving for healthy sessions and changes outcomes only for a charger that reconnects inside its window.

Note the clock is **receipt time**, not charger-measured time: a replayed queue proves the charger is alive even though the readings are old. The existing resume-staleness guard already gets this right and must keep using receipt time.

See ADR 0031 decision 3, and ADR 0022 for the invariant that backstops must fire strictly after the primary timer.

## Acceptance criteria

- [ ] A `SUSPENDED` transaction whose charger checked in recently is not finalized when its original window would have expired
- [ ] A transaction that has genuinely gone silent for the full window is still finalized as today
- [ ] The derived stale-suspended sweep and resume-staleness cutoffs remain strictly later than the primary timer, per-row (ADR 0022 invariant preserved)
- [ ] `suspended_at` is no longer the measured column, and any reconnect path that rewrote it no longer needs to
- [ ] The pathological-flap guard still bounds a charger that reconnects repeatedly with no energy progress
- [ ] Existing disconnect, resume, staleness and sweep suites stay green

## Blocked by

None - can start immediately
