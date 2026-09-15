> **SUPERSEDED (2026-08-27) by [[adr-0028-customer-facing-charger-code]].**
> This directory is the *planning* record from 2026-07-31. The format it locked
> (`VOW-S{station}-C{seq}`, a per-station sequence frozen for the charger's life)
> is not what ships. Nor is the `S006C02` bay-derived form drafted on 2026-08-24 —
> that draft is now a rejected option in the ADR. The shipping identifier is the
> **Asset Code**: a system-allocated running number with a per-environment series —
> `VOW0001` production, `VOWS0001` staging and development. It bears no relation to
> `Charger.name`; the one-time backfill merely seeds from the stencils already on the
> fleet so existing labels stay valid. Serviceability moved out of the identifier
> entirely and into `Charger.purpose`. Read `docs/adr/0028-customer-facing-charger-code.md`
> and the **Asset Code** / **Charger Purpose** entries in `CONTEXT.md` as the
> current spec; the backfill lives in `.scratch/charger-asset-code/`.
> Kept for the rejected-options history only. Do not implement from this directory.

# Map: Charger display identity for customers

Labels: wayfinder:map
Driver: jeethjoseph

## Destination

A locked, implementation-ready spec for customer-facing charger identity: every
customer surface (GST invoice PDF, /my-charges, /my-sessions, /charge/[id], UPI
payee/description line, /stations) shows the charger **name** (recognition) plus a
new **immutable station-prefixed display code** (correctness), and a customer never
sees the `charge_point_string_id` UUID again. Done when the spec can be handed to
/to-prd + /to-issues with nothing left to decide.

## Notes

- Planning only — this map produces decisions and a spec, not code. Implementation
  happens after handoff via /to-issues.
- Skills per session: /grilling and /domain-modeling for HITL tickets.
- Tracker: local markdown (this directory). No native blocking → tickets carry a
  `Blocked-by:` line in the body. Claim = `Assignee:` line.
- Repo invariants that bind the eventual spec: Aerich-only migrations, UTC-store /
  IST-render timestamps, env-var checklist (CLAUDE.md). GST invoice rows are frozen
  tax snapshots — never retro-edited.
- Staging data facts (verified 2026-07-31 via SSM): `name` holds operator asset
  codes (`VOW0001`…, one with trailing space), `charge_point_string_id` is always a
  UUID, `external_charger_id` is inconsistent (UUID copy / vendor serial / null).
  All 9 staging chargers sit in one station (`IDT_Staging`, id 1). Prod not yet
  inspected (SSM call blocked by permission classifier this session).

## Decisions so far

- [Charter decisions (grilling, 2026-07-31)](issues/00-charter-decisions.md) — label's job is recognition + support + compliance; keep free-form `name`, add a synthetic unique display code; scheme is station-prefixed numeric `S{station}-C{seq}`, auto-generated, immutable for life, backfilled by migration; all customer surfaces in scope; GST invoice gets new name+code snapshot columns, already-issued invoices stay frozen.
- [Lock the display-code format string](issues/01-lock-code-format.md) — `VOW-S{station}-C{seq}`, 2-digit zero-pad widening past 99, regex `^VOW-S\d{2,}-C\d{2,}$`, 11 chars typical; VOW continues the fleet's stencil convention; one canonical serializer, no hand-formatting.

## Not yet specified

- **Final spec assembly** — once the open tickets close, fold everything into a
  PRD (/to-prd) and slice into implementation issues (/to-issues). Likely also an
  ADR (charger display identity) alongside ADR 0008's two-field state precedent.
- **Migration/backfill execution plan** — Aerich migration shape, backfill
  ordering SQL, whether the dirty staging names (trailing space) get a cleanup
  migration. Specifiable after [01](issues/01-lock-code-format.md) and
  [02](issues/02-seq-allocation-and-backfill.md).
- **Per-surface rendering strings + API contract** — exact label per surface and
  which endpoints gain a `charger_code` field. Specifiable after
  [01](issues/01-lock-code-format.md) and [03](issues/03-name-hygiene-and-fallback.md).

## Out of scope

- Retro-editing already-issued GST invoices — ruled out in the charter: frozen tax
  documents stay byte-identical.
- Enforcing uniqueness on charger `name` (globally or per station) — superseded by
  the display-code decision; names stay free-form.
- Admin/franchisee UI redesign beyond the minimum needed for support to resolve a
  code (that minimum is [06](issues/06-support-lookup-of-code.md)).
- Repurposing or cleaning up `external_charger_id` — inconsistent legacy field,
  untouched by this effort.
