# Frontend active-session card on `/my-charges`

Status: ready-for-agent

## Parent

`.scratch/active-session-on-my-charges/PRD.md`

## What to build

Surface the customer's in-progress QR session(s) as a card stack at the top of the VPA search results on `/my-charges`. Card is read-only per ADR 0006 — no stop button, no action affordances.

### Data wiring

- New TanStack Query hook (e.g. `usePublicQRActiveSessions`) calling `GET /api/public/qr-active-sessions?vpa=<vpa>`.
- `refetchInterval: 15_000` while the tab is visible. Use `document.visibilityState` (e.g. via a `useEffect` hook that wires `visibilitychange` and re-keys the query, or TanStack's `refetchIntervalInBackground: false` if it satisfies the requirement).
- Hook is only enabled when `searchedVpa` is non-empty.

### Component

`ActiveSessionCard` rendering state-conditional UI. Pseudo-shape:

```
[ Status pill ]   VOW0001 · IDT_Staging          Started 21 May, 12:26 pm
                  Operator: Arunraj R

[Charging / Paused / Stopping]:
┌──────────────────────┬──────────────────────┐
│ Energy delivered     │ Spent so far         │
│ 1.57 kWh             │ ₹41.55               │
├──────────────────────┴──────────────────────┤
│ ⚡ 7.2 kW   ⏱ 14 min                          │
├─────────────────────────────────────────────┤
│ Refund if you stop now:        ₹8.45        │
│ [█████████░░░░] Budget: ₹41.55 / ₹50.00     │
└─────────────────────────────────────────────┘

[Waiting]:
₹50.00 paid · waiting to start
Plug in your car to start charging. We'll auto-refund if you don't plug in within N minutes.
```

State-conditional details:

- **Waiting** — status pill `Waiting to plug in` (amber). Show `amount_paid` headline + plug-in copy. No KPIs.
- **Charging** — status pill `Charging` (green). Full KPI grid + budget bar + refund line.
- **Paused** — status pill `Paused` (amber). Full KPI grid, `power_kw` renders as `0 kW`, helper line: "Charger lost contact — auto-resumes when it reconnects."
- **Stopping** — status pill `Stopping…` (gray/blue). Full KPI grid + budget bar, helper line: "Wrapping up — final bill in a moment."

Duration ticks client-side every 1s without re-polling the endpoint (compute from `started_at`).

### Layout placement

Insert the active-session list **above the status filter** in the VPA search results section of `app/my-charges/page.tsx`. Render nothing when the array is empty. When the user changes the VPA via `Change`, the active-session query is reset alongside the history query.

### Types

Add the new response shape to `lib/api-services.ts` mirroring the backend `01-backend-qr-active-sessions-endpoint.md` schema.

## Acceptance criteria

- [ ] Active session card appears at the top of search results when the backend reports `data.length > 0`.
- [ ] Each of the four sub-states (`waiting`, `charging`, `paused`, `stopping`) renders the documented copy and field visibility.
- [ ] Multi-session: two backend entries render as two stacked cards in order returned.
- [ ] Polling: card updates within ~15s of a new MeterValue landing on the backend; polling pauses when the tab is hidden and resumes on visibility change.
- [ ] Duration ticks every 1s without piggybacking on the network poll.
- [ ] Frontend production build (`cd frontend && npm run build`) passes per CLAUDE.md — no `@typescript-eslint/no-unused-vars` or `react/no-unescaped-entities` regressions.

## Blocked by

`.scratch/active-session-on-my-charges/issues/01-backend-qr-active-sessions-endpoint.md`
