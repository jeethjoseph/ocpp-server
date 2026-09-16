# Alert on OCPPLateStopRecorded

Status: ready-for-human

## What to build

A New Relic alert condition on the `OCPPLateStopRecorded` custom event that issue 01 now emits. Without it the event is a number nobody looks at, and the whole point of recording reported energy was to measure what the write-off policy costs and to catch charger-side meter persistence failing in the field.

This is a New Relic task, not a code change. The `newrelic` CLI is authenticated locally under the `voltlync` profile against account `7468195`; prod and staging share the account and are split by `appName`. There is currently one alert policy ("Diagnostic Bundles — charger log loss", id 7923440). Either add a condition there or create a sibling policy for offline continuity — a separate policy is cleaner since more conditions from this workstream will follow (monotonicity violations from issue 05, offline-start-enabled from issue 06).

Two conditions are worth having, not one:

- **Any late stop on prod.** A single `OCPPLateStopRecorded` with `appName` = prod in a 24h window. Low volume today because no continuity firmware is deployed yet, so any hit before rollout is a bug in the guard or a charger replaying a queue we did not expect — both worth a human look.
- **Gap magnitude.** `sum(gap_kwh)` over 24h above a threshold to be chosen — this is the write-off cost signal. Pick the threshold after the first week of continuity firmware in the field, not before; leave it as a dashboard widget until then.

**Also cover (added 2026-09-15):** `OCPPMeterMonotonicityViolation` (issue 05 — any occurrence on prod is a charger-side meter persistence failure; alert on count ≥ 1 per 24h, attributes `charger_id`, `transaction_id`, `previous_kwh`, `current_kwh`, `delta_kwh`) and `OCPPSessionLimitPushed` where `outcome != 'accepted'` on a charger known to run continuity firmware (issue 04).

Also add the `Custom/OCPP/LateStop/GapKwh` metric and the `OCPPLateMeterValuesStored` event to the offline-continuity dashboard so the gap is visible over time, not only when it trips.

Event attributes available: `charger_id`, `transaction_id`, `status`, `billed_energy_kwh`, `reported_energy_kwh`, `gap_kwh`.

## Acceptance criteria

- [ ] A NRQL alert condition fires on any `OCPPLateStopRecorded` from the prod app, routed to the same notification channel as the bundle-loss policy
- [ ] A dashboard widget charts `gap_kwh` over time, split by `appName`
- [ ] The gap-magnitude threshold decision is recorded here once continuity firmware has a week of field data
- [ ] The policy or condition id is recorded in `reference_newrelic_cli_access` memory or the runbook so the next workstream issue can extend it

## Blocked by

None - can start immediately
