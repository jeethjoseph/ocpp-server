Status: done

# Firmware updates: surface `error_message` on failed updates

## What to build

When a firmware update fails, `FirmwareUpdate.error_message` records why — but it is never rendered. Today an admin sees only a failed `status` and has to hit the API or read backend logs to find the reason. Close the loop by surfacing `error_message` wherever a firmware update's status is shown.

Show the error reason for any update whose status is failed/error:
- **Firmware management page** (`/admin/firmware`) — the in-progress / active updates table.
- **Charger detail page** (`/admin/chargers/[id]`) — the recent firmware updates list.

Keep non-failed rows unchanged. For a failed row, present the `error_message` inline (e.g. a red sub-line or an info/tooltip affordance next to the status), so the failure reason is visible without leaving the page.

Note one gap to close along the way: `error_message` is returned by `FirmwareUpdateResponse` and typed on `FirmwareUpdate`, but it is **not** part of the `UpdateStatusDashboard.in_progress` item shape used to populate the firmware page's active-updates table. Add `error_message` (and confirm `status` carries failure states through) to that dashboard item — backend response model + frontend type — so the management-page table actually has the field to render. This is a thin additive change, no migration.

Data already exists at the model + base-response layer:
- `FirmwareUpdate.error_message` (model) → `backend/models.py` (FirmwareUpdate)
- `FirmwareUpdateResponse.error_message` (API) → `backend/routers/firmware.py`
- `FirmwareUpdate.error_message` (TS type) → `frontend/types/api.ts`

## Acceptance criteria

- [ ] On `/admin/firmware`, a failed firmware update shows its `error_message` inline in the active/in-progress table
- [ ] On `/admin/chargers/[id]`, a failed firmware update in the recent-updates list shows its `error_message`
- [ ] `error_message` is added to the `UpdateStatusDashboard.in_progress` item shape (backend response model + frontend type) so the firmware page has the field to render
- [ ] Non-failed updates render unchanged (no empty error affordance, no layout shift)
- [ ] `null`/empty `error_message` on a failed row renders gracefully (e.g. a generic "Update failed" with no broken element)
- [ ] Frontend render test covers a failed update with a message and a failed update without one
- [ ] `docker exec ocpp-backend pytest` passes for affected backend test files (baseline: the 6 known `gst_rate_percent` flakes per CLAUDE.md)
- [ ] `cd frontend && npm run build` passes (full production build, per CLAUDE.md)

## Blocked by

None - can start immediately. Independent of issue 02 (different field, different views).
