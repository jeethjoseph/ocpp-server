# Persist VPA in localStorage on `/my-charges`

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Remember the last VPA the user searched on `/my-charges` so they don't have to re-type it on return visits. **Pre-fill, do not auto-search** — one tap on the search button is still required.

- On mount, read `localStorage["voltlync.lastVpa"]`. If non-empty and valid against `VPA_PATTERN`, set the input value (`vpaInput` state) but leave `searchedVpa` empty so nothing renders until the user taps search.
- On successful search (i.e. when `searchedVpa` is set after the form submit), persist the trimmed/lowercased VPA to `localStorage["voltlync.lastVpa"]`.
- When the user taps `Change` (`handleReset`), remove the key from localStorage along with clearing the in-memory state.
- Guard all localStorage access with a `typeof window !== 'undefined'` check (Next.js SSR safety).

## Acceptance criteria

- [ ] After a successful search, refreshing the page pre-fills the VPA input but the page renders the unauthenticated empty state until search is tapped.
- [ ] Tapping `Change` clears both the input and the stored VPA — refresh after that shows an empty input.
- [ ] Malformed values that somehow land in localStorage (e.g. a stale key from before validation existed) are ignored on read.
- [ ] No SSR runtime errors (`localStorage is not defined`) — Next.js production build (`cd frontend && npm run build`) passes.

## Blocked by

None — can ship independently of issues 01 and 02. (Provides a UX improvement on its own even before the active-session card exists.)
