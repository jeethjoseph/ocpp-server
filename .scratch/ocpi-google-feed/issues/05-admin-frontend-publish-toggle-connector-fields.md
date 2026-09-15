# Admin frontend: publish toggle UI + structured connector enum fields

Status: ready-for-agent

## What to build

Admin UI for the OCPI publish workflow, on top of the issue-04 backend.

**Publish toggle (charger detail):**
- A `publish_to_google` toggle on the charger detail page.
- When the completeness gate would block (backend returns the missing-fields error), the toggle is disabled or shows a clear "cannot publish yet — missing: …" state listing the unmet requirements (coords/city/address, `ocpi_evse_id`, connector `ocpi_standard`).
- A confirmation step on enabling, surfacing that publishing has irreversible-in-identity consequences (the `evse_id` is permanently spent).
- Reflect the current published state and show the resolved `ocpi_evse_id` (read-only).

**Connector enum fields (connector create/edit):**
- Add `ocpi_standard`, `ocpi_format`, `ocpi_power_type` as select inputs (enum-bound) and `max_voltage` / `max_amperage` as numeric inputs.
- Keep the existing `connector_type` field as a display-only label (per [ADR 0016](../../../docs/adr/0016-connector-ocpi-normalization.md)); make clear it is cosmetic.

## Acceptance criteria

- [ ] Charger detail shows publish state, the read-only `ocpi_evse_id`, and a toggle wired to the issue-04 endpoint.
- [ ] When the gate is unmet, the UI clearly lists the missing fields and prevents/blocks enabling; a successful enable shows a confirmation of irreversible-identity consequences first.
- [ ] Connector create/edit form has the five OCPI fields (enum selects + numeric), validated client-side and persisted via the backend API.
- [ ] Timestamps shown (e.g. audit/last-published) render in **IST** via the canonical converter (per CLAUDE.md), not raw UTC.
- [ ] `cd frontend && npm run build` passes (full production build, not just `tsc`/scoped lint).
- [ ] `docs/v1/llm-context-document.md` and the comprehensive architecture doc updated to describe the OCPI admin surface.

## Blocked by

- 04 (publish toggle endpoint + connector OCPI write API)

## Comments

**2026-09-01 — checked by tracker audit; CONFIRMED STILL OPEN.** The audit's first pass
grouped this with likely-complete work; hand-verification disagreed. No OCPI code exists anywhere in `backend/` or `frontend/` — the whole feature is unstarted, not just this slice.

Method: `.scratch/tracker-reconciliation/REPORT.md`.
