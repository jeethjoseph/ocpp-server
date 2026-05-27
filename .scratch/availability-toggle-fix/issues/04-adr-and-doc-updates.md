Status: ready-for-agent

# ADR 0008 + doc updates: availability is separate from latest_status

## What to build

Capture the architectural decision so future contributors don't unify `availability` and `latest_status` again. Add ADR 0008. Update CLAUDE.md and the v1 comprehensive architecture doc to reflect the two-field model.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Skip the ADR — "the column name is self-documenting" | Fails on all three ADR criteria. The split is non-obvious from the schema alone (why two state fields?), hard to reverse once consumers rely on it, and the result of a real Option A/B/C tradeoff during the fix. Future maintainer will absolutely ask "can we simplify these into one?" without context |
| Only update CLAUDE.md, skip the ADR | CLAUDE.md is for working conventions, not architectural decisions. ADR is the right home for the rationale |
| Defer doc updates until the next "doc sweep" PR | This is the moment the decision is fresh. Documenting later means details get lost |

## What to change

### `docs/adr/0008-charger-availability-separate-from-status.md` (new)

Mirror the format of existing ADRs (`docs/adr/0001` through `0007`). Skeleton:

```markdown
# Charger availability is separate from latest_status

`Charger.availability` (admin-set intent: Operative/Inoperative) and `Charger.latest_status` (OCPP-reported state: Available/Preparing/Charging/Faulted/Unavailable/etc.) are two independent fields. Do not unify them. The toggle in the admin UI reads `availability`; the status pill and any operational/billing logic reads `latest_status`.

Rationale: a charger can be admin-set Operative AND reporting Faulted at the same time (the admin wants it available; the hardware is broken). A Charging charger that an admin clicks Inoperative goes to `availability=Inoperative` immediately, but `latest_status` stays Charging until the session ends per OCPP Scheduled semantics.

## Considered alternatives

- **Single `latest_status` field, derive admin intent from audit log.** Rejected: every consumer of `latest_status` would need to learn the new derivation. Surfaced as bug on 2026-05-27 where toggle appeared broken because charger Accepted ChangeAvailability but didn't transition state — admins clicked repeatedly with no effect.
- **Optimistic write to `latest_status` on Accepted (Option A in the fix design).** Rejected: would mask legitimate Faulted/Charging states and conflict with the next StatusNotification. The conceptual split was already in the codebase comments (see `frontend/app/admin/chargers/page.tsx:104-110`); we just hadn't pushed it into the schema.
- **TriggerMessage:StatusNotification after Accepted (Option C).** Rejected: only papers over the bug for cooperative chargers. Real-world firmware sometimes Accepts ChangeAvailability without transitioning state — TriggerMessage doesn't help that case.

## Consequences

- The toggle UI is permanently decoupled from charger-reported state. Admins see their last command reflected, regardless of whether the charger acknowledged with a follow-up StatusNotification.
- A future contributor looking at the schema and seeing two fields with similar names will reasonably ask "why?" — this ADR is the answer.
- The franchisee endpoint (`routers/franchisee_portal.change_availability`) and admin endpoint (`routers/chargers.change_charger_availability`) both write to `availability`; their UX vocabularies stay different per [the parallel-endpoint rationale in the comprehensive arch doc / earlier comments] but their persisted effect converges.
- If business requirements ever need per-connector availability (currently `connector_id` is fixed to 0 in the admin endpoint), this column will need to move to `Connector` or be supplemented with a `ConnectorAvailability` table. That's a separate ADR if/when it happens.
```

### `CLAUDE.md`

Add a section near the existing Database tier section or under a new heading. Tight version:

```markdown
## Charger state model (two fields, intentionally)

The `charger` table carries TWO orthogonal state-shaped fields. They are NOT redundant.

- `latest_status` (`ChargerStatusEnum`): what the charger reports via OCPP `StatusNotification`. Values: `Available`, `Preparing`, `Charging`, `SuspendedEVSE`, `SuspendedEV`, `Finishing`, `Reserved`, `Unavailable`, `Faulted`. Driven entirely by the `StatusNotification` handler.
- `availability` (`ChargerAvailabilityEnum`): what an admin/franchisee has commanded via the `ChangeAvailability` endpoint. Values: `Operative`, `Inoperative`. Persisted on `Accepted`/`Scheduled` OCPP responses by `routers/chargers.change_charger_availability` and `routers/franchisee_portal.change_availability`.

The admin UI toggle reads `availability`. The status pill and OCPP routing read `latest_status`. See ADR 0008 for the full rationale.
```

### `docs/v1/llm-context-document.md`

Add to the "Database tier" section, after the SSL contract subsection:

```markdown
### Charger state — two orthogonal fields

The `charger` row carries `latest_status` (OCPP-reported, ChargerStatusEnum) and `availability` (admin-commanded, ChargerAvailabilityEnum). They are independent — a Faulted charger can be admin-set Operative; a Charging charger can be admin-set Inoperative (transition is deferred until the session ends per OCPP Scheduled semantics). The admin/franchisee toggle reads `availability`; everything else reads `latest_status`. See ADR 0008.
```

### `docs/v1/comprehensive-architecture-documentation.md`

If a "Charger control surface" section exists (referenced in `routers/chargers.py:737`), extend it. Otherwise add a new subsection under the Database section explaining the two-field model.

## Verification

- `docs/adr/0008-charger-availability-separate-from-status.md` exists and follows the format of `0007`
- `CLAUDE.md` includes the new section
- `llm-context-document.md` and `comprehensive-architecture-documentation.md` updated
- No other doc changes — this is the focused doc PR

## Definition of done

- ADR 0008 written and merged
- CLAUDE.md updated
- Both v1 docs updated
- PR merged to `develop`
