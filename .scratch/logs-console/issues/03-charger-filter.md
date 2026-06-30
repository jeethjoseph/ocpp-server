# Charger filter

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. Searchable single-select ChargerCombobox wired to charge_point_id param + URL state, default "All chargers".

## What to build

Add a **Charger** filter to the **Logs Console** — a single-select, searchable charger picker that narrows the log list to one charger.

End-to-end behaviour:

- The `GET /api/admin/logs` endpoint accepts an optional `charge_point_id` param and filters server-side (the `(charge_point_id, timestamp)` index from the MVP slice backs this).
- A single-select, **searchable** charger picker on the page (typeahead by `charge_point_id`, ideally surfacing station/name for recognisability). Default state is "All chargers" = no charger filter.
- The selected charger is reflected in the URL query string (`?charger=<id>`) alongside the existing action filter, and ANDs with it.

## Acceptance criteria

- [ ] `GET /api/admin/logs?charge_point_id=<id>` filters to that charger and composes (AND) with the action filter
- [ ] Searchable single-select charger picker on the page, defaulting to "All chargers"
- [ ] Charger selection is reflected in and restored from the URL query string
- [ ] `cd frontend && npm run build` passes

## Blocked by

- #02 Logs Console MVP — Action filter, end-to-end

## Comments

- 2026-06-24 (QA): Picker showed "No matches" — `useChargers({limit:1000})` 422'd against the endpoint's `le=100` cap. Fixed: `limit:100` + debounced server-side `search` param so it works beyond the 100-row cap. Build passes.
