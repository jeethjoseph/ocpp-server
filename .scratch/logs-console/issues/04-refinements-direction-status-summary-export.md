# Refinements: direction/status + summary + export

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. In-memory IN/OUT + errors-only refinement; summary shows "Showing X of N fetched" + server total + IN/OUT counts; CSV export = visible rows.

## What to build

Round out the **Logs Console** with the in-memory refinements and the derived displays.

End-to-end behaviour:

- **Direction (IN/OUT)** and **status (errors-only, i.e. status != SUCCESS)** refine the already-fetched, action+charger-narrowed window **in memory** — no new server params.
- **Summary counts** describe what the user is currently looking at: they start from the server's action/charger-filtered `total`/`has_more` and update further as the in-memory direction/status refinements are applied. The header must never disagree with the visible rows.
- **CSV export honours all active filters** (action + charger + in-memory direction/status) — export equals what's on screen.
- When in-memory refinement hides rows, surface it honestly (e.g. "showing X of N fetched") rather than silently shrinking the count. `has_more`/`total` stay server-truthful.

## Acceptance criteria

- [ ] IN/OUT and errors-only controls refine the visible rows in memory
- [ ] Summary header reflects the currently-visible population (server filter + in-memory refinement)
- [ ] CSV export contains exactly the rows currently shown, under all active filters
- [ ] An honest "showing X of N fetched" indicator appears when refinement hides rows
- [ ] `cd frontend && npm run build` passes

## Blocked by

- #02 Logs Console MVP — Action filter, end-to-end
