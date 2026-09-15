# Raise the suspend window magnitudes

Status: ready-for-human

## What to build

Raise the **Suspend window** values now that the clock measures silence rather than session age.

The latched value is agreed at roughly **48 hours**. **The unlatched value is not decided** and needs a human call — that is why this is separate from the mechanism.

The per-connector-type split from ADR 0027 **survives unchanged**. Its reasoning still holds precisely because the window now only ever applies when we know nothing: a latching connector locks the cable into the vehicle inlet, so the car is probably still attached; an unlatched socket can be pulled by anyone walking past. Only the numbers move.

Values live in the git-tracked policy module, not env vars, per ADR 0027 — a change here is a reviewed diff and a deploy, deliberately.

Consider on the way: ADR 0027 recorded a flap-guard ceiling of 36 h (3 zero-progress resets × 12 h). At 48 h that arithmetic becomes 6 days, and the silence clock removes the ceiling entirely for a charger showing progress. Decide whether a hard session-age ceiling is now wanted as a separate backstop.

## Acceptance criteria

- [ ] Latched and unlatched values agreed and recorded, with the unlatched figure justified
- [ ] Values changed in the git-tracked policy module; no env override introduced
- [ ] Derived sweep and staleness cutoffs track the new values automatically
- [ ] A decision recorded on whether a hard session-age ceiling is wanted
- [ ] ADR 0027 amended (not reversed) to carry the new magnitudes

## Blocked by

- `02-suspend-window-measures-silence.md`
