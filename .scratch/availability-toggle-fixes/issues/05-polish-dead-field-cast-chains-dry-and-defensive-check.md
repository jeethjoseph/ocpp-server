# Polish: dead `note` field, cast chains, DRY, defensive data.success check

Status: ready-for-agent

## What to build

Four small cleanup items flagged in the senior review of issues 01 + 02. Each is <10 lines; bundled because separately they'd be PR-noise.

### Delete backend `note` field

The admin `change_charger_availability` endpoint returns `"note": "Scheduled" if ocpp_status == "Scheduled" else None`. After issue 01, the frontend reads `ocpp_response` directly and ignores `note`. No other consumer in the codebase. Delete the field from the response payload.

### Fix frontend cast chains

`frontend/lib/queries/chargers.ts` uses two escape-hatch casts:
- `response as unknown as ChangeAvailabilityResponse` in the `mutationFn` — because `chargerService.changeAvailability` is typed `Promise<ApiResponse>` (the generic) and the real shape is wider.
- `context as ChangeAvailabilityContext` (three times) — because TanStack Query's context generic isn't plumbed through `useMutation`.

Fix at the source:
- Parameterize `chargerService.changeAvailability` to return `Promise<ChangeAvailabilityResponse>` (move the type into a shared location, e.g., `types/api.ts` or a co-located module).
- Pass the context generic to `useMutation<TData, TError, TVariables, TContext>` so `onSuccess` / `onError` receive a properly typed context without casts.

### DRY: `handleChangeAvailability` calls `getAvailabilityToggleState`

Both functions currently have `currentStatus !== "Unavailable"`. The second should call the first:

```ts
const isCurrentlyOperational = getAvailabilityToggleState(currentStatus);
```

Catches a future drift between the two.

### Defensive `data.success` check in the hook

The backend always returns `success: true` on the HTTP success path, but the hook reads `data?.ocpp_response` without checking `data.success` first. Add the guard so a future contract change where `success: false` slips through with a 200 doesn't silently process as Accepted.

## Acceptance criteria

- [ ] Admin endpoint response no longer includes a `note` field. (Verified by hitting the endpoint or by inspecting the handler.)
- [ ] `frontend/lib/queries/chargers.ts` has zero `as unknown as` casts in the `useChangeAvailability` hook.
- [ ] `useMutation` call site uses the full 4-generic form so `context` is properly typed.
- [ ] `handleChangeAvailability` in `frontend/app/admin/chargers/page.tsx` uses `getAvailabilityToggleState` for the operational check — no duplicated comparison.
- [ ] Hook's `onSuccess` branch only proceeds when `data.success === true`; otherwise routes to a defensive error toast + rollback.
- [ ] `npm run build` + `npm run test:run` + backend pytest all green.

## Blocked by

Issue 04 (pre-deploy blockers).
