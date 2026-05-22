# Frontend availability-toggle: honour OCPP response status, drop Faulted-conflation, debounce

Status: ready-for-agent

## What to build

The admin charger-availability toggle currently lies to operators in two of three OCPP response cases and conflates an orthogonal status field with availability. Three real bugs, all in the frontend, fixed in one PR.

### B1 — `Rejected` is treated as success

Backend returns `200 { success: true, ocpp_response: "Rejected" }` when the charger refuses the change. The `useChangeAvailability` hook's `onSuccess` handler unconditionally fires `toast.success(\`Charger marked as ${status}\`)`, never reads `ocpp_response`. Combined with the optimistic UI update, the displayed state is wrong until the next refetch. Operator believes the charger flipped; it didn't.

### B2 — `Scheduled` is treated as immediate

Per OCPP 1.6, if a transaction is in progress the charger returns `Scheduled` and applies the change only after StopTransaction. The frontend currently shows the same "marked as ..." success toast as for `Accepted`, and the optimistic update sticks. Operator believes the charger is offline; customer is still pulling kWh.

### B3 — `Faulted` conflated with `Unavailable`

`isCurrentlyOperational = currentStatus !== "Unavailable" && currentStatus !== "Faulted"` treats a Faulted charger as "off-and-toggleable-on." Per OCPP 1.6, Faulted is a hardware/error state, orthogonal to availability. A Faulted charger CAN still be Operative (availability-wise); the toggle will misread its state and any flip attempt will likely Reject.

### L2 — Rapid-click spam

No client-side debounce. Multiple rapid clicks fire multiple ChangeAvailability requests. Not catastrophic (OCPP is idempotent per-state) but messy and inflates the audit log.

### Plan

In `lib/queries/chargers.ts:useChangeAvailability`:

- Branch `onSuccess` on `data.ocpp_response`:
  - `"Accepted"` → green toast (`"Charger marked as ${status}"`); keep optimistic update.
  - `"Scheduled"` → blue/info toast (`"Change scheduled — will apply when the current session ends"`); **revert the optimistic update** (next StatusNotification will reconcile the real state when the session ends).
  - `"Rejected"` → red error toast (`"Charger refused the change"`); **revert the optimistic update**.
  - Anything else (defensive) → neutral toast with the raw OCPP status; revert.
- The rollback path for the optimistic update already exists in `onError`; extract it into a shared helper so `onSuccess` Rejected/Scheduled branches can call it too.

In `app/admin/chargers/page.tsx`:

- Drop `&& currentStatus !== "Faulted"` from `isCurrentlyOperational` in both `getAvailabilityToggleState` and `handleChangeAvailability`. A Faulted charger now shows as "operational" (because OCPP availability is orthogonal to fault state); operators can still try to toggle it and the OCPP layer surfaces the actual response per the branching above.
- The button itself: while `toggleLoadingChargers.has(chargerId)` is true, disable the button. (May already be the case — verify.) This is the L2 debounce: prevents the spam by making the user wait for the round-trip.

## Acceptance criteria

- [ ] OCPP `Accepted` → success toast, optimistic update stays.
- [ ] OCPP `Scheduled` → info-style toast mentioning "will apply when the current session ends", optimistic update reverts.
- [ ] OCPP `Rejected` → error toast, optimistic update reverts.
- [ ] Faulted chargers display the toggle as the inverse of `Unavailable` only (no longer treated as off-by-default).
- [ ] Button visibly disabled (e.g. greyed/spinner) while a request is in flight for that charger; rapid clicks don't fire multiple requests.
- [ ] No new console warnings in the dev server.
- [ ] `cd frontend && npm run test:run` passes (existing tests + any new component tests for the branching logic, if the maintainer judges the branching worth testing at the hook level — `useMutation` testing is heavy, so an integration check via Playwright/E2E would be a better future fit; for this PR, manual click-through is acceptable).
- [ ] `cd frontend && npm run build` passes.

## Blocked by

None — can start immediately.
