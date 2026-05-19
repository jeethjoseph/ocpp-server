# Frontend test harness bootstrap (Vitest + React Testing Library)

Status: ready-for-agent

## What to build

**L5 — the frontend has no test infrastructure.** Build velocity verification rests entirely on `next build` (type-checks + lint-checks) plus manual click-through. The synthetic-fee work added two pure-function helpers (`formatTariffRangeAllIn`, `breakdownAllInTariff`) and one component (`TariffBreakdownPreview`) whose correctness is meaningful — they encode the customer-facing pricing contract — but none of them have automated regression protection on the frontend side. The backend equivalents (`back_derive_rate_per_kwh`, `synthetic_*` helpers) are tested; the frontend mirrors are not.

This issue bootstraps the harness AND writes the first meaningful tests, so future contributors have a working template instead of a greenfield setup task.

### Framework choice

**Vitest + React Testing Library + jsdom.** Vitest is the modern default for Next.js / Vite-era projects: native ESM, fast, Jest-compatible API surface so anyone with Jest experience is productive immediately. React Testing Library is the canonical companion for component tests. Jest works too but adds Babel/SWC config friction we don't need.

### First tests to ship with the harness

The point of a tracer-bullet harness is to PROVE the setup works with real tests, not just config files. Ship these alongside the config:

1. **`breakdownAllInTariff` (pure function, `lib/utils.ts`)** — same fixtures as the backend's `test_back_derive_30_at_18_pct_gst_and_2_pct_fee` so the frontend mirror stays in sync. Cover the worked example (₹25 → rate ≈ ₹20.7627, gateway ≈ ₹0.50, GST ≈ ₹3.7373) plus the `null` guard on invalid input.
2. **`formatTariffRangeAllIn` (pure function, `lib/utils.ts`)** — single value (uniform tariffs), range (varied), both-null (returns `"N/A"`), one-null collapses cleanly.
3. **`TariffBreakdownPreview` (component, `app/admin/chargers/page.tsx`)** — render with a known input value, assert the three breakdown rows display the right rupee figures; render with an empty/invalid value, assert it doesn't render. Use RTL's `render` + `screen.getByText`.

### Plan

- `npm install --save-dev vitest @testing-library/react @testing-library/jest-dom @vitejs/plugin-react jsdom`
- Add `frontend/vitest.config.ts` with React plugin, jsdom env, and a `setupFiles` entry pointing at `@testing-library/jest-dom/vitest`.
- Add `"test": "vitest"` and `"test:run": "vitest run"` scripts to `frontend/package.json`. The `:run` variant exits when done (for CI).
- Add `frontend/__tests__/lib/utils.test.ts` and `frontend/__tests__/components/TariffBreakdownPreview.test.tsx` (or co-locate as `frontend/lib/utils.test.ts` — pick the convention used elsewhere in the repo if anything similar exists; otherwise `__tests__/` is standard).
- Add a short `frontend/__tests__/README.md` (or update `frontend/README.md` if it exists) explaining: how to run tests, where they live, the convention for adding new ones, and a note that pure functions + components touching customer-facing math are highest-priority test targets.
- Verify CI: if there's a CI config (`.github/workflows/`, `.gitlab-ci.yml`, etc.) that runs `npm run build`, add `npm run test:run` alongside. If no CI exists, skip — the harness is still useful locally.

### Out of scope for this issue

- Comprehensive component coverage (huge surface; the harness landing is the prerequisite for incremental backfill).
- E2E / Playwright (different problem; out of "unit/component tests" scope).
- Snapshot tests (we prefer explicit assertions; the codebase can adopt snapshots later if a use case emerges).

## Acceptance criteria

- [ ] `cd frontend && npm test -- --run` runs and passes, with at least the three test files described above (utils + component).
- [ ] The three breakdown-rate fixtures from the conversation (₹25 / ₹100 / ₹500 all-in at 18% GST + 2% fee) produce assertions matching the backend's `test_back_derive_30_at_18_pct_gst_and_2_pct_fee` to ±0.01.
- [ ] `vitest` + `@testing-library/react` versions pinned in `frontend/package.json` (no floating `^` on majors for these — testing libraries break regularly).
- [ ] Brief docs explain how to run tests and where to add new ones.
- [ ] If a CI config exists, the test step is added alongside the build step. Otherwise document the gap (e.g., "no CI today — run `npm run test:run` locally before pushing").
- [ ] `cd frontend && npm run build` still passes (regression guard — the test setup shouldn't break the production build).

## Blocked by

Slice 4 (doc + label hygiene + preview refactor). Reason: Slice 4 refactors `TariffBreakdownPreview` to accept `feePercent` / `gstPercent` as props. Writing the component test against the pre-refactor signature is wasted work; writing it against the post-refactor signature gives a more useful test. Transitively also blocked by Slice 1 (since Slice 4 is).
