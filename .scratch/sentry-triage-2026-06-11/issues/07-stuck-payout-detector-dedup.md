# Dedup/cooldown stuck-payout detector alerts

Status: ready-for-agent

Sentry: OCPP-BACKEND-3 — `Stuck franchisee payouts: N entries for franchisee X` (413 occurrences, warning)

## What to build

The stuck-payout detector (`StuckPayoutDetector`) emits a Sentry warning for every franchisee that has commission-ledger entries stuck past the threshold with retries exhausted. It runs on a schedule and re-fires the same warning for the same stuck set every pass, with no dedup — hence 413 warnings for what is a small, static set of stuck entries. The repeated alerts drown the signal and make it impossible to tell "still stuck" from "newly stuck".

Add dedup/cooldown so the same stuck set does not re-alert on every detection pass: e.g. only alert when the stuck set for a franchisee changes, or at most once per cooldown window per franchisee. The detector must still alert promptly when a *new* franchisee or *new* entries become stuck.

This issue is the alerting-hygiene fix only. The actual cleanup of franchisee 2's current stuck entries is tracked separately (see issue 08).

## Acceptance criteria

- [ ] A stable set of stuck entries for a franchisee no longer emits a warning on every pass; it respects a dedup key or cooldown window.
- [ ] A newly stuck franchisee, or a change in the stuck set, still alerts within one detection cycle.
- [ ] The detector's return value (count of stuck entries) is unchanged.
- [ ] Test covers: (a) repeated passes over an unchanged set suppress duplicate alerts, (b) a changed/new set re-alerts.
- [ ] `docker exec ocpp-backend pytest` passes for the affected test file(s).

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** `StuckPayoutDetector` keeps in-memory `_alert_state` per franchisee (stuck entry-id frozenset + last-alert time); `_should_alert` re-alerts only on a changed set or after `alert_cooldown_hours` (env `STUCK_PAYOUT_ALERT_COOLDOWN_HOURS`, default 24h). Franchisees no longer stuck are forgotten so they re-alert immediately if they recur. `_sweep_once` refactored into `_should_alert`/`_emit_alert` (each <40 lines). Tests: `test_unchanged_stuck_set_does_not_realert_each_pass`, `test_changed_stuck_set_realerts_within_one_cycle`. Pass.
