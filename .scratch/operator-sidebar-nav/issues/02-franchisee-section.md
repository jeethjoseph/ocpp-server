# Franchisee section adopts the sidebar

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. app/franchisee/layout.tsx feeds the franchisee item array (+icons) into SidebarShell. Build passes.

## What to build

Bring the franchisee section onto the sidebar shell built in #01.

End-to-end behaviour:

- `app/franchisee/layout.tsx` renders the shared `Sidebar` shell with the franchisee link array (Dashboard, Stations, Transactions, Settlements, QR Codes, Profile — each with an icon).
- Franchisee routes inherit the same desktop-fixed / mobile-drawer behaviour and bottom account block.
- The root frame already excludes `/franchisee*` from the top-bar + centered column (set up in #01) — confirm it applies.

## Acceptance criteria

- [ ] Franchisee routes render with the left sidebar and the franchisee link set; no top navbar on those routes
- [ ] Desktop-fixed / mobile-drawer behaviour and the account block work identically to admin
- [ ] Customer/public and admin routes unaffected
- [ ] `cd frontend && npm run build` passes

## Blocked by

- #01 Sidebar shell + root reframe, proven on the admin section
