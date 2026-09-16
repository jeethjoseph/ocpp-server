# The suspend window measures silence, not session age

Status: done

## What to build

Change what the **Suspend window** clock measures. It currently counts from `suspended_at` — effectively session age once suspended — so a session is force-finalized at the window even if the charger has been checking in throughout. Under [[offline-charging-continuity]] that kills sessions we can see are alive.

Measure instead the time since we last heard **anything about that transaction**. Every check-in resets it. The window then governs only the no-information case, which is what it was always meant to answer.

Consequence to accept deliberately: there is no upper bound on session duration while a charger keeps reporting. That is correct — advancing energy is proof of life, and the money is bounded by the **Budget cap** regardless.

Keep the current magnitudes in this slice. Raising them is a separate decision (see the blocked-by note on the magnitudes issue) so the mechanism does not wait on an undecided number. This slice is therefore behaviour-preserving for healthy sessions and changes outcomes only for a charger that reconnects inside its window.

Note the clock is **receipt time**, not charger-measured time: a replayed queue proves the charger is alive even though the readings are old. The existing resume-staleness guard already gets this right and must keep using receipt time.

**Derive the silence clock; do not add a column for it.** The brief pencilled in a migration 64 `last_contact_at` on `transaction`. Rejected on the write path: keeping it current means a `transaction` row write on every `MeterValues` frame, the highest-frequency path in the system. `is_resume_too_stale` already computes silence with no column — the newest of `suspended_at`, the latest `MeterValue.created_at`, and `start_time` — and that computation becomes the single silence helper every consumer calls. The sweep keeps `suspended_at` only as its cheap candidate pre-filter and then checks each candidate's derived silence; `SUSPENDED` rows are few, so a per-row lookup is fine. The in-memory timers drop their `suspended_at` compare-and-swap: on fire, recompute silence, and if the charger has checked in, re-arm for the remainder instead of finalizing.

**Flap guard rule, stated.** A check-in without energy progress is still "heard from", so the silence clock alone would let a charger that flaps forever with a stuck meter hold a session open indefinitely. Keep `MAX_RESETS_WITHOUT_PROGRESS` and give it one precise meaning: once a transaction has reconnected that many times with no energy advance, a check-in **without** energy progress no longer resets the silence clock; only advancing energy does. The zero-energy watchdog already zeroes the counter on progress, so a healthy long session with cellular flake never trips it.

See ADR 0031 decision 3, and ADR 0022 for the invariant that backstops must fire strictly after the primary timer.

## Acceptance criteria

- [x] A `SUSPENDED` transaction whose charger checked in recently is not finalized when its original window would have expired
- [x] A transaction that has genuinely gone silent for the full window is still finalized as today
- [x] The derived stale-suspended sweep and resume-staleness cutoffs remain strictly later than the primary timer, per-row (ADR 0022 invariant preserved)
- [x] `suspended_at` is no longer the measured column, and any reconnect path that rewrote it no longer needs to
- [x] The pathological-flap guard still bounds a charger that reconnects repeatedly with no energy progress: past `MAX_RESETS_WITHOUT_PROGRESS`, only advancing energy resets the silence clock
- [x] Silence is computed by one shared helper from existing columns; no `last_contact_at` column and no migration
- [x] A timer that fires while the charger has checked in re-arms for the remaining window rather than finalizing
- [x] Existing disconnect, resume, staleness and sweep suites stay green

## Blocked by

None - can start immediately

## Shipped 2026-09-15

**Finding first.** The clock was already silence-based for the signal that matters, through a mechanism ADR 0031 did not name: a `MeterValues` frame for a `SUSPENDED` transaction resumes it to `RUNNING`, and the next disconnect re-suspends it with a fresh `suspended_at` and a fresh timer. The old timer's compare-and-swap then skipped. So no in-window session that sent readings was ever killed by session age. What remained was structural: two implementations of "how long since we heard" (the sweep read `suspended_at` alone, the guard read the max of three), timers keyed on `suspended_at` equality after a DB round trip, and a Boot-only view of "heard from".

**Built.** `disconnect_handler.last_heard_at` / `silence_seconds` — the newest of `suspended_at` and the latest `MeterValue.created_at`, with `start_time` as a fallback only (letting it compete in the max made a freshly created row look heard-from; caught by the existing staleness tests). Consumers: `hold_until_silent` (the one timer, armed by `arm_suspend_timer` from both the disconnect path and `ChargePoint._suspend_timeout` on Boot; sleeps the window, re-checks, re-arms for the remainder if heard from, exits if no longer `SUSPENDED`; arming again replaces the previous timer), `finalize_stale_suspended_transactions` (pre-filters on `suspended_at`, decides on silence), `is_resume_too_stale` (delegates). No column, no migration.

**Decision recorded.** A Heartbeat, StatusNotification or bare WebSocket reconnect does not extend the window: it says the charger is alive, not the session, and continuity firmware replays immediately on reconnect. Boot still counts by re-stamping `suspended_at`, capped by `MAX_RESETS_WITHOUT_PROGRESS`; past the cap only a reading moves the clock, and a reading with no energy progress is the zero-energy watchdog's job.

Tests: `test_silence_clock.py` (9). 197 green across the affected suites. `ChargePoint._suspend_timeout` lost its `original_suspended_at` argument; two connector-trait assertions updated.
