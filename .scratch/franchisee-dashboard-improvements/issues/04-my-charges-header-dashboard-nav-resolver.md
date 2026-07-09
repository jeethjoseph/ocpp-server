# 04 — /my-charges header + Dashboard link + sign-in resolver redirect

Status: ready-for-agent

## What to build

Make the public `/my-charges` page role-aware: a minimal header hosting a Dashboard link for staff and a sign-in affordance for guests, plus a sign-in-scoped redirect that sends staff to their portal without trapping them away from `/my-charges`.

- **Minimal header** on `/my-charges` (the page has none today): brand + right-side auth area.
  - **Guest** (signed out) → **Sign In** button.
  - **Signed-in ADMIN/FRANCHISEE** → a **Dashboard** link pointing at their portal (reuse the existing `homeHref` logic: ADMIN→`/admin`, FRANCHISEE→`/franchisee`) + user menu.
  - **Signed-in USER** → user menu, **no** Dashboard link (they have no portal).
- **Sign-in-scoped redirect** via a **post-sign-in resolver route** targeted by Clerk `forceRedirectUrl` from the `/my-charges` sign-in flow. The resolver reads role and routes: **ADMIN→`/admin`, FRANCHISEE→`/franchisee`, USER→`/my-charges`**.
- Because only the sign-in flow targets the resolver, an already-signed-in admin/franchisee who *navigates* to `/my-charges` is **not** redirected — they stay and use the Dashboard link. (This is the deliberate reconciliation of "show a Dashboard link on /my-charges" with "redirect staff on sign-in" — do not collapse it into an always-redirect, which would make the Dashboard link unreachable.)

## Acceptance criteria

- [ ] `/my-charges` has a header; guests see a Sign In button
- [ ] Signed-in ADMIN/FRANCHISEE see a Dashboard link to their portal (via homeHref); USER does not
- [ ] Signing in from `/my-charges` redirects ADMIN→/admin, FRANCHISEE→/franchisee, USER→/my-charges
- [ ] An already-signed-in ADMIN/FRANCHISEE navigating to `/my-charges` is NOT redirected and can use the Dashboard link
- [ ] `/my-charges` remains publicly accessible (no auth required to view)
- [ ] `cd frontend && npm run build` passes

## Blocked by

- None - can start immediately
