# Frontend tests

Vitest + React Testing Library + jsdom.

## Running

```bash
cd frontend
npm test          # watch mode (interactive)
npm run test:run  # one-shot (CI-friendly; exits when done)
```

Tests live under `frontend/__tests__/` and follow the directory layout of
the code they cover. Vitest auto-discovers `__tests__/**/*.test.{ts,tsx}`.

## What's tested today

| File | Covers | Why it's here |
|---|---|---|
| `lib/utils.test.ts` | `formatTariffRangeAllIn`, `breakdownAllInTariff` | Customer-facing pricing math (ADR 0001 / 0003). The backend's `back_derive_rate_per_kwh` has equivalent test fixtures in `backend/tests/test_tariff_all_in_migration.py` — keep them in sync if you change the formula. |
| `components/TariffBreakdownPreview.test.tsx` | Admin form's live back-derivation preview | Verifies labels reflect props (no hardcoded percentages) and the breakdown renders for valid input + suppresses for invalid input. |

## Adding new tests

Highest-priority targets are **pure functions** and **components that touch
customer-facing money or pricing math**. Anything that controls what a
customer sees on the invoice or pays on the QR screen should have a test
mirroring the backend's coverage.

Co-locate by domain — e.g., tests for `lib/foo.ts` go in
`__tests__/lib/foo.test.ts`, tests for `components/Foo.tsx` go in
`__tests__/components/Foo.test.tsx`.

## Conventions

- **Pure-function tests** use direct `expect().toBe()` / `toBeCloseTo()`.
- **Component tests** use React Testing Library's `render` + `screen.getByText`.
  Prefer queries that mirror what a user would search for (accessible name,
  visible text) over implementation details (CSS selectors, test IDs).
- **No snapshots.** They drift silently after `vitest -u` becomes muscle memory.
  Write explicit assertions instead.
- **No E2E.** Out of scope for this harness. Add Playwright as a separate
  initiative if needed.

## Gotchas

- The Vitest config disables PostCSS (`css: { postcss: { plugins: [] } }`)
  because Tailwind v4's plugin format crashes Vite's CJS loader. Tests don't
  render styles anyway. If you start asserting on computed CSS, revisit this.
- Versions are pinned without `^` in `package.json` — testing libraries break
  on minor bumps regularly. Upgrade deliberately.

## CI

The repo has no CI configuration today (no `.github/workflows/`,
`.gitlab-ci.yml`, etc.). When CI is added, include `npm run test:run`
alongside `npm run build` in the frontend step. Until then, run both
locally before pushing changes that touch `frontend/`.
