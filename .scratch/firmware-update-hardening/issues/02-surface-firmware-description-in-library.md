Status: done

# Firmware Library: surface the `description` field admins enter at upload

## What to build

The `FirmwareFile.description` field is captured at upload time and stored, returned by the API, and typed on the frontend — but it is never rendered. Admins can write a description (release notes / changelog) when uploading firmware but can never read it back in the UI.

Close the loop end-to-end by surfacing `description` in the Firmware Library on `/admin/firmware`. Keep the library table itself lean: show the full description in an **expandable row or detail popover** rather than a fixed column, so long release notes have room to breathe without breaking the table layout.

Data already flows at every layer:
- `FirmwareFile.description` (model) → `backend/models.py` (FirmwareFile)
- `FirmwareFileResponse.description` (API) → `backend/routers/firmware.py`
- `FirmwareFile.description` (TS type) → `frontend/types/api.ts`

So this is a **render-only** slice — no schema, migration, or API change required. The only work is in the frontend Firmware Library component plus a render test.

## Acceptance criteria

- [ ] Each firmware row in the Firmware Library on `/admin/firmware` can reveal its full `description` via an expandable row or detail popover
- [ ] Rows with an empty/`null` description render gracefully (e.g. em-dash or "No description", no broken layout, no expand affordance that opens to nothing)
- [ ] Long, multi-line descriptions wrap and remain readable without breaking the table layout
- [ ] A frontend render test covers: a row with a description (text visible on expand) and a row without (graceful empty state)
- [ ] `cd frontend && npm run build` passes (full production build, per CLAUDE.md — tsc + scoped lint are not sufficient)

## Blocked by

None - can start immediately.
