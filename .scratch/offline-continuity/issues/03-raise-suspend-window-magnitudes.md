# Raise the suspend window magnitudes

Status: done

## What to build

Raise the **Suspend window** values now that the clock measures silence rather than session age.

The latched value is agreed at roughly **48 hours**. **The unlatched value is not decided** and needs a human call — that is why this is separate from the mechanism.

The per-connector-type split from ADR 0027 **survives unchanged**. Its reasoning still holds precisely because the window now only ever applies when we know nothing: a latching connector locks the cable into the vehicle inlet, so the car is probably still attached; an unlatched socket can be pulled by anyone walking past. Only the numbers move.

Values live in the git-tracked policy module, not env vars, per ADR 0027 — a change here is a reviewed diff and a deploy, deliberately.

Consider on the way: ADR 0027 recorded a flap-guard ceiling of 36 h (3 zero-progress resets × 12 h). At 48 h that arithmetic becomes 6 days, and the silence clock removes the ceiling entirely for a charger showing progress. Decide whether a hard session-age ceiling is now wanted as a separate backstop.

## Acceptance criteria

- [x] Latched and unlatched values agreed and recorded, with the unlatched figure justified
- [x] Values changed in the git-tracked policy module; no env override introduced
- [x] Derived sweep and staleness cutoffs track the new values automatically
- [x] A decision recorded on whether a hard session-age ceiling is wanted
- [x] ADR 0027 amended (not reversed) to carry the new magnitudes

## Blocked by

- `02-suspend-window-measures-silence.md`

## Decided and shipped 2026-09-15

**48 h latched / 12 h unlatched. No hard session-age ceiling.**

Evidence (read-only SSM query, prod + staging, every session the previous windows killed in the last 90 days, measuring time until the charger's next inbound OCPP message):

| Population | n | median | p90 | max | ≤12h | ≤48h |
|---|---|---|---|---|---|---|
| latched, prod | 6 | 6.1h | 22.5h | 28.8h | 4 | 6 |
| latched, staging | 9 | 1.2h | 23.1h | 41.3h | 6 | 9 |
| unlatched, prod | 10 | 71m | 6.3h | 15.8h | 9 | 10 |
| unlatched, staging | 32 | 93m | 6.3h | 20.6h | 30 | 32 |

Reasoning: under ADR 0031 the window is "how long we hold money before writing off"; a pulled plug on an unlatched socket is a flat meter that bills nothing, so the old cable-security argument for 45 min no longer applies and the remaining cost of a longer window is refund latency on an abandoned session. 12 h captures 93% of unlatched outages and keeps that wait to half a day. Ceiling: advancing energy is proof of life and money is bounded by the Budget cap; the flap guard caps a reboot-without-replay charger at ~4 windows, which under continuity is a meter-persistence failure for issue 05 to alert on.

Changed: `backend/policy.py` constants + rationale comment; ADR 0027 amendment banner; `test_resume_staleness_guard` derives its past-the-window ages from the constant instead of a literal 13h. Derived sweep/staleness cutoffs track automatically (ADR 0022 invariant preserved). 82 tests green across the window suites.
