# Deep-link + retire per-charger path

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. Charger detail page deep-links to /admin/logs?charger=<id>; ChargerLogs component + /logs/charger/{id} & /summary endpoints removed; docs updated.

## What to build

Make the **Logs Console** the single home for OCPP message logs and remove the now-redundant per-charger embedded viewer.

End-to-end behaviour:

- The charger detail page replaces its embedded `ChargerLogs` viewer with a **"View OCPP logs →"** deep-link to `/admin/logs?charger=<id>` (pre-filtered to that charger via the URL state and charger filter from earlier slices).
- Retire the per-charger endpoints `GET /logs/charger/{id}` and `GET /logs/charger/{id}/summary` and remove the embedded `ChargerLogs` component (and any now-dead query hooks/services).
- Update the docs: `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` to describe the Logs Console and the retired per-charger path.

## Acceptance criteria

- [ ] Charger detail page shows a "View OCPP logs →" deep-link to `/admin/logs?charger=<id>`; embedded log viewer removed
- [ ] `/logs/charger/{id}` and `/logs/charger/{id}/summary` endpoints removed; no remaining callers
- [ ] Dead frontend code (component, hooks, services) for the old viewer removed
- [ ] `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md` updated
- [ ] `cd frontend && npm run build` passes; backend tests for the removed endpoints cleaned up

## Blocked by

- #02 Logs Console MVP — Action filter, end-to-end
- #03 Charger filter
