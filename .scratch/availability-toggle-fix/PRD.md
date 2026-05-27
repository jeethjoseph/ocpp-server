# Charger availability toggle: persist admin intent separately from OCPP status

## Summary

The admin "availability toggle" in the chargers list page reads `Charger.latest_status` to decide its visual state, and the change-availability endpoint sends an OCPP `ChangeAvailability` message but **does not persist anything to the DB**. When a charger Accepts the command but doesn't send a follow-up `StatusNotification` (common across real-world firmware), the toggle appears un-responsive — admins click repeatedly with no visible effect.

Add a dedicated `Charger.availability` field that captures admin-set intent and survives independently of `latest_status` (which continues to reflect what the charger actually reports). Frontend toggle reads the new field; OCPP status semantics are untouched.

## Why now

Surfaced on 2026-05-27 against charger `ffeadb01-78bc-4b6e-b5cd-1ff657cbedbc` (id=4) on staging: two `ChangeAvailability:Operative` calls in ~1 min, both `Accepted` at the OCPP layer, but `latest_status` stayed `Unavailable` and the toggle never flipped. Verified the same shape exists on prod — schema and code paths are identical.

This isn't a one-charger firmware quirk. Every charger model in the wild has some path where ChangeAvailability is Accepted without an immediate StatusNotification follow-up, so the bug is structurally guaranteed.

## Scope

**In scope:**
- New `Charger.availability` column with values `Operative`/`Inoperative`
- Migration with `Operative` default for all existing chargers
- Both admin (`routers/chargers.py`) and franchisee (`routers/franchisee_portal.py`) `change-availability` endpoints persist the new field on `Accepted` OCPP responses
- Frontend toggle in `/admin/chargers/` and `/franchisee/chargers/{id}` reads the new field
- Backend tests for endpoint behavior
- ADR 0008 documenting the availability-vs-status split

**Explicitly out of scope:**
- Per-connector availability (we still operate at whole-charger granularity; matches existing contract per `routers/chargers.py:743-751`)
- Backfill of historical admin intent from audit log (no reliable signal; existing rows default to `Operative` and admins can re-toggle if they want Inoperative)
- Touching `latest_status` semantics — it continues to be driven exclusively by `StatusNotification` handler
- Faulted-state interaction (Faulted is already orthogonal to availability per the existing UI comment)

## Architecture

### Two distinct concepts, two columns

| Concept | Column | Driven by | Meaning |
|---|---|---|---|
| **Operational status** | `latest_status` (`ChargerStatusEnum`) | OCPP `StatusNotification` from charger | What the charger reports it's doing right now: `Available`, `Preparing`, `Charging`, `Faulted`, `Unavailable`, etc. |
| **Admin availability** | `availability` (`ChargerAvailabilityEnum`) — NEW | Admin/franchisee `ChangeAvailability` click on `Accepted` | What an authorized user has commanded the charger to be: `Operative` or `Inoperative` |

The two are orthogonal:
- A `Faulted` charger can still be `Operative` (the admin wants it available; the hardware is broken)
- A `Charging` charger that the admin clicks `Inoperative` on goes to `availability=Inoperative` immediately; the actual `latest_status` flips to `Unavailable` only after the current session ends (OCPP `Scheduled` response semantics)
- The toggle button reads `availability`, not `latest_status` — so admin intent is reflected back to the admin even if the charger hasn't yet reported a state change

### Why not Option A (optimistic `latest_status` update)?

Considered and rejected. Setting `latest_status = Operative → "Available"` on Accepted overrides what the charger actually reports — would mask Faulted states, mask Charging-in-progress states, and conflict with the next legitimate `StatusNotification`. The conceptual split is in the codebase already (see `frontend/app/admin/chargers/page.tsx:104-110` comment); we just need to surface it in the schema.

### Why not Option C (`TriggerMessage:StatusNotification` after Accepted)?

Considered. Adds OCPP message volume and only papers over the problem — for chargers whose firmware doesn't respond to the original ChangeAvailability with a state transition, TriggerMessage probably won't either. Option B fixes the user-visible bug for **every** charger regardless of firmware quirks.

## Locked decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | New `ChargerAvailabilityEnum` with two values: `Operative`, `Inoperative` | Matches OCPP vocabulary already used in `change-availability` admin endpoint |
| 2 | Column added via Aerich migration; default `Operative` for backfill | Matches CLAUDE.md policy. Optimistic default — assume existing `Unavailable` chargers got there via the charger, not via admin |
| 3 | Update both admin and franchisee endpoints to persist on `Accepted` | The two endpoints have intentionally different UX (per `routers/chargers.py:732-737`); only the DB-write logic unifies |
| 4 | `Rejected` and other non-Accepted OCPP responses do NOT update the column | The admin intent isn't actuated — don't persist a state that didn't take effect |
| 5 | Frontend toggle reads `charger.availability`, not `latest_status` | Single field, single source of truth for the toggle |
| 6 | ADR 0008 documents the availability-vs-status split | Hard to reverse + surprising-without-context + real trade-off — meets all three ADR criteria |
| 7 | `latest_status` semantics untouched | Only the toggle reads `availability`; everything else (status pill, charger health, OCPP routing) keeps reading `latest_status` |

## Phases (one PR each, in order)

- **Issue 01** — Migration + model update. Pure schema change. No behavior change.
- **Issue 02** — Backend endpoints persist `availability` on Accepted. Frontend still reads `latest_status`. Tests added.
- **Issue 03** — Frontend toggle switches to read `availability`. Build verification. The user-visible fix lands here.
- **Issue 04** — ADR 0008 + doc updates.

Each PR is independently safe to merge — the toggle keeps working (with the original bug) until issue 03 ships.

## Rollback

If `availability` column causes any issue in production:
1. Frontend can be reverted independently — toggle resumes reading `latest_status` (old behavior + old bug)
2. Backend persistence can be no-op'd via a feature flag or by reverting the endpoint changes
3. The column itself can stay — having a vestigial column is harmless until decommission

The migration is `add column with default`, which is a metadata-only operation in Postgres 11+ (default value is fast-path with no table rewrite). Zero-downtime rollout.

## Cost impact

Zero. Pure code change. No new infrastructure.

## Testing

| Test | Asserts |
|---|---|
| `test_change_availability_operative_sets_column` | POST with `type=Operative` and OCPP Accepted → `Charger.availability == Operative` |
| `test_change_availability_inoperative_sets_column` | POST with `type=Inoperative` and OCPP Accepted → `Charger.availability == Inoperative` |
| `test_change_availability_rejected_does_not_update` | OCPP Rejected response → column unchanged |
| `test_change_availability_audit_log_includes_new_value` | Audit log `changes` JSON includes `new_availability` |
| `test_status_notification_does_not_touch_availability` | Incoming StatusNotification updates `latest_status` only |
| `test_franchisee_change_availability_also_persists` | Franchisee endpoint behaves same as admin |

Frontend: smoke test in browser after build — `/admin/chargers` shows toggle reflecting `availability` field.

## Issues

See `issues/` for the breakdown.

- `01-add-availability-column.md` — Aerich migration + model
- `02-persist-availability-in-endpoints.md` — Backend endpoint changes + tests
- `03-frontend-toggle-reads-availability.md` — Frontend toggle + build verification
- `04-adr-and-doc-updates.md` — ADR 0008 + CLAUDE.md + comprehensive arch doc updates
