# Backend availability-toggle: connector_id hardening, audit snapshot race, admin/franchisee divergence doc

Status: ready-for-agent

## What to build

Three small backend fixes around the availability-toggle endpoints. All in the same routers; one PR.

### M2 — `connector_id` not validated against existing connectors

`routers/chargers.py:change_charger_availability` accepts `connector_id: int = Query(..., ge=0)` and forwards it to the OCPP message without validating that the connector actually exists on the target charger. A request with `?connector_id=99` against a charger that has connectors 1 and 2 sends a doomed OCPP message and gets back `Rejected` (or unspecified behavior depending on firmware). The admin UI hardcodes `connectorId: 0` (whole-charger semantic per OCPP 1.6), so individual-connector control isn't a product surface — but the backend's permissiveness lets ops/curl typos cause confusing failures.

**Decision (from grilling Q2):** admin operates at whole-charger granularity only. Per-connector toggle is not a roadmap item for the foreseeable future.

**Fix:** tighten the validation. Accept `connector_id` in the schema but reject anything other than `0` for the admin endpoint with a 422 (or 400) and a clear message: *"Admin availability toggle operates at charger level only (connector_id must be 0)."* This keeps the OCPP-aligned vocabulary in the query string while preventing the foot-gun.

(The franchisee endpoint at `routers/franchisee_portal.py:change_availability` already hardcodes `connector_id=0` internally — no change needed there.)

### M4 — Audit `previous_status` snapshot race

`current_status = charger.latest_status` is read on line 730, then the OCPP exchange happens, then the audit row is written on line 753-760. If a `StatusNotification` lands from the charger between those two points, the captured `previous_status` is stale relative to the actual state the operator clicked on.

The race window is small but real and the field is meant to be ops' reference for "what state was the charger in when the operator clicked the button." Fix: re-fetch `charger.latest_status` immediately before composing the audit payload (or just read it inline at audit-write time). One line.

### M1 — Document the admin/franchisee API divergence

Two `changeAvailability` shapes coexist:
- `lib/api-services.ts:120` (admin) — `(id, type: "Operative"|"Inoperative", connectorId)`, query string `?type=...&connector_id=N`. Mirrors OCPP vocabulary.
- `lib/api-services.ts:902` (franchisee) — `(chargerId, available: boolean)`, query string `?available=true|false`. Operator-intuitive boolean.

Backend endpoints follow the same split. **Decision (from grilling Q3):** keep them divergent — admins are debugging an OCPP layer and want explicit Operative/Inoperative vocabulary; franchisees want a self-serve boolean.

**Fix:** add docstring comments at the top of both endpoint handlers explaining the divergence is intentional, cross-linking each other. Drop a one-paragraph note in `docs/v1/comprehensive-architecture-documentation.md` under a "Charger control surface" section so future contributors don't try to "DRY" them into one shape.

## Acceptance criteria

- [ ] `POST /api/admin/chargers/{id}/change-availability?connector_id=1&type=Operative` returns 400 (or 422) with a message naming the constraint.
- [ ] `POST /api/admin/chargers/{id}/change-availability?connector_id=0&type=Operative` continues to work.
- [ ] Audit log row's `previous_status` reflects the charger's state read inside the audit-write critical section, not the snapshot taken before the OCPP round-trip.
- [ ] Both `change_charger_availability` (admin) and `change_availability` (franchisee) handlers carry docstrings explicitly noting the contract divergence and cross-linking.
- [ ] One paragraph in `docs/v1/comprehensive-architecture-documentation.md` documenting the divergence as intentional.
- [ ] Existing `test_change_availability` continues to pass (calls with `connector_id=1` will need updating to `connector_id=0`).

## Blocked by

None — can start immediately. Issue 03 depends on this landing so the new tests assert against the new behavior.
