# Derive the resume-staleness threshold from the disconnect window (retire MAX_RESUME_GAP_SECONDS)

Status: done

## What to build

Per **ADR 0022**. `transaction_finalizer.is_resume_too_stale` currently compares
the activity gap against an independently-configured `MAX_RESUME_GAP_SECONDS`
env var (default 900). Because it is a separate number, it can be — and was —
set below `DISCONNECT_SUSPEND_TIMEOUT_SECONDS`, inverting the invariant and
force-finalizing chargers that reconnect inside their legitimate window
(`STALE_RECONNECT`). Real casualty: prod txn 870 (VOW0008) reconnected at 18m12s
inside the 30-min window, got killed, and forced the customer to pay a second QR
session (871).

Change `is_resume_too_stale` to take its threshold from
`disconnect_handler.stale_suspended_cutoff_seconds()`
(= `max(DISCONNECT_SUSPEND_TIMEOUT, SUSPEND_TIMEOUT) + buffer`) — the same
computed cutoff both stale-suspended sweeps already share — instead of
`MAX_RESUME_GAP_SECONDS`. This makes `guard ≥ primary` structurally guaranteed;
the misordering becomes unrepresentable.

Retire `MAX_RESUME_GAP_SECONDS`: remove the code default, the three
`docker-compose*.yml` `backend.environment:` entries, and the `.env*.example`
lines. Update the `CLAUDE.md` env-var checklist count.

## Acceptance criteria

- [ ] `is_resume_too_stale` derives its threshold from `stale_suspended_cutoff_seconds()`; no reference to `MAX_RESUME_GAP_SECONDS` remains in code.
- [ ] `MAX_RESUME_GAP_SECONDS` removed from all three compose files and all `.env*.example` files.
- [ ] Regression test: a disconnect-suspended txn reconnecting at `DISCONNECT_SUSPEND_TIMEOUT + small` **resumes** (not `STALE_RECONNECT`); one reconnecting past the derived cutoff is still refused. Assert at the `is_resume_too_stale` seam.
- [ ] Existing suites stay green: `test_resume_staleness_guard`, `test_disconnect_resume_integration`, `test_disconnect_handler`, `test_billing_retry_stale_suspended`, `test_transaction_finalizer`.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test files.

## Blocked by

None — ADR 0022 is accepted.

## Comments

**Implemented 2026-07-06.** `is_resume_too_stale` (`transaction_finalizer.py`) now derives its threshold from `disconnect_handler.stale_suspended_cutoff_seconds()` (lazy import, no cycle); the `MAX_RESUME_GAP_SECONDS` constant + `import os` removed. Purged from all three compose files, `.env.staging.example`, `.env.prod.example`, `backend/.env.example`, and the main.py log message. Tests updated to use the derived `THRESHOLD`; `test_threshold_is_configurable` → `test_threshold_tracks_derived_cutoff` (patches the derived source), and a new `test_derived_cutoff_exceeds_disconnect_timer` pins the ADR 0022 invariant (the txn 870 regression). 30/30 pass across test_resume_staleness_guard, test_transaction_finalizer, test_disconnect_handler, test_disconnect_resume_integration, test_billing_retry_stale_suspended. Note: derived cutoff in prod = max(1800,300)+60 = 1860 (was env-set 2100); still > 1800, invariant holds, and the guard rarely fires anyway (sweep at 1860 beats it).

Scope is the resume-ordering fix only. The reconciliation/"refund-on-stale-reading"
concern is **latent** (odometer sweep 2026-07-06 proved no deployed charger
delivers energy during a blackout) and is explicitly out of scope — see ADR 0022
scope note. Behavior-preserving for correctly-configured prod/staging (already
run 2100 ≈ derived 1860).
