# Frontend resilience: loading/error UI, adaptive polling, shared clock, threshold copy

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Several connected UX hardening items on the `/my-charges` active-session experience.

- **Loading + error UI.** Today the active-session block renders nothing when the query is loading or errored, so transient backend failures are silent. Add a small loading skeleton (similar visual weight to a single card) shown only on the *first* load (subsequent polls don't flash skeleton). Add a small error banner with a `Retry` button when the query is in error state.
- **Adaptive polling.** When the backend returns `total === 0`, drop the poll interval from 15s to 60s. When `total > 0` again, snap back to 15s. Continue to pause entirely when the tab is hidden.
- **Shared 1s clock.** Today `useElapsedSince` creates one `setInterval` per card. Hoist it to a tiny context provider mounted at the page level so N cards share one timer.
- **Threshold copy.** Use the new `stale_threshold_seconds` field from the API to render specific waiting-state copy: "We'll auto-refund in N minutes if you don't plug in." Replace the hardcoded "a few minutes."
- **`formatINR` fallback.** Update the helper to return `"—"` instead of `null` when the input is null/invalid, and update its type signature so callers can render `₹${formatINR(x)}` safely.
- **Namespace localStorage key.** Rename `localStorage["voltlync.lastVpa"]` → `localStorage["voltlync.myCharges.lastVpa"]`. Add a one-time read-and-migrate path so existing users don't lose their stored VPA.

## Acceptance criteria

- [ ] First-load shows a skeleton; subsequent polls update silently without UI flicker.
- [ ] Backend 5xx triggers a visible error banner with a working `Retry` action.
- [ ] Empty result polls at 60s; non-empty result polls at 15s; both pause on `visibilitychange`.
- [ ] Multiple active cards share a single 1s timer (verified by adding two cards and counting `setInterval` calls in a test or by code inspection).
- [ ] Waiting state copy shows a specific remaining-minutes value, computed from `stale_threshold_seconds`.
- [ ] `formatINR(null)` returns `"—"`; no instance of `₹null` can render.
- [ ] Existing-user localStorage migration works: after the deploy, a stored value at the old key transparently appears at the new key on first mount.
- [ ] Frontend production build (`cd frontend && npm run build`) passes.

## Blocked by

- `.scratch/active-session-on-my-charges/issues/06-api-contract-cleanup.md` (introduces `stale_threshold_seconds`)
