# Sidebar shell + root reframe, proven on the admin section

Status: done
Type: AFK
Resolution: Implemented 2026-06-23. Shared SidebarShell (logo/icon-nav/bottom account block, desktop-fixed + mobile drawer), AppFrame root reframe (top bar + centered main only off operator routes), app/admin/layout.tsx with admin items+icons. Build passes.

## What to build

Replace the crowded top navbar with a left **sidebar shell** for the admin section, building the shared infrastructure end-to-end. This is the tracer bullet: it proves the whole layout architecture through one operator section.

End-to-end behaviour:

- A shared, parameterized **`Sidebar`** component fed a link array (each item gains an icon). Layout: logo at the top, icon + label nav links in the middle, and an **account block pinned to the bottom** carrying the Clerk `UserButton`, the role badge, and the theme toggle.
- **Responsive**: on md+ the sidebar is fixed/persistent; on mobile it's an off-canvas drawer over a dimmed backdrop, opened by a hamburger in a mobile-only top strip (logo + hamburger) and closed on link-tap or backdrop-tap. Built lightweight (no shadcn `Sheet` exists in the project).
- **Root reframe**: the root layout stops unconditionally wrapping everything in the top `Navbar` + `max-w-7xl` centered `<main>`. A small client frame applies the top-bar + centered column only to non-operator routes, returning bare children for `/admin*` (and, later, `/franchisee*`) so a per-section layout owns the chrome.
- **`app/admin/layout.tsx`** renders the sidebar shell with the admin link array.

The customer/public top nav must remain exactly as-is.

## Acceptance criteria

- [ ] Admin routes render with a left sidebar (logo, icon nav, bottom account block); no top navbar on those routes
- [ ] Sidebar is fixed on desktop (md+) and an off-canvas drawer on mobile (hamburger opens it; link-tap and backdrop-tap close it)
- [ ] `UserButton`, role badge, and theme toggle work from the sidebar account block
- [ ] Customer/public routes are visually unchanged (top navbar + centered column intact) — regression-checked
- [ ] Sidebar component is parameterized by a link array (not hardcoded to admin)
- [ ] `cd frontend && npm run build` passes

## Blocked by

None - can start immediately.
