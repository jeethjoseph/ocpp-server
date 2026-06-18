Status: done

# Bulk "Deploy to chargers" dialog on the Firmware Library

## What to build

Give admins a way to deploy one firmware version to many chargers at once, from the **Firmware Library** on `/admin/firmware`. Each firmware row gains a "Deploy to chargers" action that opens a multi-step dialog driving the hardened bulk deploy endpoint (issue 04).

Flow:

1. **Pick** — a searchable charger picker, filterable/groupable by **station**. Each charger row shows its current firmware version and an online/offline badge. The badge is **informational only** — offline chargers are valid targets (they update when they reconnect), so online state must not gate selection. Chargers already on the firmware version being deployed are **auto-excluded** (shown greyed with "already on <version>", not selectable). "Select all" selects **all rows matching the current filter** (not the literal fleet), with the live count shown.
2. **Review** — a deliberate confirmation beat restating the action before anything fires: "Deploy <version> to N chargers across M stations · K will be skipped." Confirm / Cancel.
3. **Result** — after firing, swap to a result view showing the endpoint's `success` / `skipped` / `failed` buckets: a one-line summary header (`N scheduled · K skipped · F failed`) plus a per-charger breakdown grouped by bucket. Skipped and failed are expanded (admins need the reasons); success collapses to a count. On close, the Active Updates table reflects the new PENDING rows.

This is a **frontend** slice on top of issue 04 — no further backend work. The picker depends on a chargers list that exposes per-charger current firmware version + station + online state; if the existing admin charger list query already returns these, reuse it, otherwise extend that query rather than adding a bespoke endpoint.

## Acceptance criteria

- [ ] Each Firmware Library row has a "Deploy to chargers" action opening the dialog
- [ ] Picker is filterable by station; each charger row shows current firmware version + online/offline badge (badge does not disable selection)
- [ ] Chargers already on the target version are visibly excluded and cannot be selected
- [ ] "Select all" selects all rows matching the current filter and shows the selected count; the primary action restates the count
- [ ] Review step shows scheduled / skipped / station counts before firing; Cancel aborts with no API call
- [ ] Result view renders `success` / `skipped` / `failed` buckets with per-charger reasons (skipped/failed expanded, success collapsed)
- [ ] After a successful deploy, the Active Updates table on the page reflects the newly scheduled PENDING rows
- [ ] Frontend render test covers: auto-excluded same-version row, select-all-within-filter count, and the three-bucket result view
- [ ] `cd frontend && npm run build` passes (full production build, per CLAUDE.md)

## Blocked by

- Issue 04 (harden the bulk firmware deploy endpoint) — the picker's auto-exclusion mirrors, and the result view renders, the `{ success, skipped, failed }` response shape defined there.
