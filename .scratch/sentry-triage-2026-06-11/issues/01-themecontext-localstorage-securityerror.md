# Guard localStorage access in ThemeContext against Safari SecurityError

Status: ready-for-agent

Sentry: OCPP-FRONTEND-5 — `SecurityError: The operation is insecure.` (production)

## What to build

The `ThemeProvider` reads `localStorage.getItem('theme')` (and writes the theme back) without any guard. On Mobile Safari (observed iOS 18.7, `app.voltlync.com/my-charges`), any access to `localStorage` throws `SecurityError: The operation is insecure.` when storage is blocked — private browsing, Intelligent Tracking Prevention, or "Block All Cookies". The unhandled throw crashes the provider during render.

Wrap every `localStorage` read and write performed by the theme provider in a safe accessor that catches the exception and falls back to the default theme (`system`) when storage is unavailable. Theme selection should still work in-memory for the session even when persistence is impossible; it simply won't survive a reload.

## Acceptance criteria

- [ ] Reading the saved theme never throws when `localStorage` access is denied; it falls back to the `system` default.
- [ ] Writing the selected theme never throws when `localStorage` access is denied; the in-session theme still updates.
- [ ] The page renders normally in a browser context where `localStorage` access raises `SecurityError` (verifiable by stubbing `localStorage` to throw).
- [ ] `cd frontend && npm run build` passes.

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11** (branch `ops/log-rotation-and-tail-default`). Added `readStoredTheme`/`writeStoredTheme` try/catch helpers in `ThemeContext.tsx`; both the initial read and the persistence write are now guarded, falling back to in-session `system` theme when storage is blocked. Verified with `cd frontend && npm run build` (passes — full ruleset).
