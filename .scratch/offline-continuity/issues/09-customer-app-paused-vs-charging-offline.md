# Distinguish "paused" from "charging offline" in the customer app

Status: ready-for-human

## What to build

Decide, then build, how a customer sees a session whose charger is unreachable but still delivering.

ADR 0027 added `SUSPENDED` to the active-session surface so a session deliberately held for hours would not vanish from the customer's app, and it renders as **PAUSED**. Under [[offline-charging-continuity]] that label is wrong: the car is charging. A customer watching their app see "paused" while their vehicle draws current is the **only user-visible consequence** of this whole workstream, and it is currently unresolved.

The product decision comes first and is genuinely open. Options worth weighing: a distinct sub-state meaning "charging, last confirmed N minutes ago"; keeping one label but showing the staleness of the reading; or accepting PAUSED as an honest statement of what the CSMS actually knows. Each trades customer reassurance against claiming more certainty than we have — we do not know the charger is delivering, we only know it probably is.

Whatever is chosen applies to both the customer app and the public QR session view, which share the sub-state vocabulary.

See ADR 0031 consequences, ADR 0027, and the customer sub-state definitions in CONTEXT.md.

## Acceptance criteria

- [ ] Product decision made and recorded, including what the label claims and what it does not
- [ ] The chosen vocabulary added to CONTEXT.md as a customer sub-state, with an avoid-list entry if a term is retired
- [ ] Customer app and public QR view render consistently — no surface left showing the old label
- [ ] A stale-but-live session is distinguishable from a genuinely paused one, or the decision to not distinguish them is explicit
- [ ] Copy does not assert energy is flowing when the CSMS cannot know that

## Blocked by

- `02-suspend-window-measures-silence.md`
