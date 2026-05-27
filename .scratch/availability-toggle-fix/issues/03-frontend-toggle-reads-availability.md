Status: ready-for-agent

# Frontend: switch availability toggle to read `Charger.availability`

## What to build

Update the admin chargers list page (`frontend/app/admin/chargers/page.tsx`) and the franchisee charger detail page (if it exposes an availability toggle) to derive the toggle's visual state from `Charger.availability` instead of `Charger.latest_status`. This is the PR that **makes the bug actually go away from a user's perspective.**

Issues 01 + 02 must already be deployed to staging before this is shipped — otherwise the frontend reads a non-existent field.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Compute availability client-side from a list of "operational" statuses | Re-creates the conceptual mistake we're trying to fix. The new column IS the right source |
| Hybrid — read `availability` if present, fall back to `latest_status` | Two code paths, two bugs to maintain. After issue 01 is deployed, `availability` is always present |
| Hide the toggle entirely if `availability` field is missing | Breaks the cutover sequence — the column is present from issue 01 onward |

## What to change

### `frontend/types/api.ts` (or wherever `Charger` is typed)

Add the new field to the `Charger` interface:

```typescript
export interface Charger {
  // ... existing fields ...
  latest_status: string;
  availability: "Operative" | "Inoperative";
  // ...
}
```

Grep for `Charger` interface declarations to make sure all of them get the new field — there may be multiple.

### `frontend/app/admin/chargers/page.tsx`

Replace `getAvailabilityToggleState` around line 104:

```typescript
// OLD
const getAvailabilityToggleState = (status: string) => {
  return status !== "Unavailable";
};

// NEW
const getAvailabilityToggleState = (charger: Charger) => {
  // Reads ADMIN-SET availability intent, NOT what the charger reports.
  // See ADR 0008 for why these are separate.
  return charger.availability === "Operative";
};
```

Update every call site of `getAvailabilityToggleState`. Two known sites:

- Line 120: `const isCurrentlyOperational = getAvailabilityToggleState(currentStatus);` — change to pass the full charger object
- Line 391: `Toggle availability (${getAvailabilityToggleState(charger.latest_status) ? ...})` — pass the charger

Update `handleChangeAvailability` signature if it currently takes `currentStatus: string` — switch to `currentCharger: Charger`:

```typescript
const handleChangeAvailability = async (charger: Charger) => {
  const isCurrentlyOperational = getAvailabilityToggleState(charger);
  const newType: "Inoperative" | "Operative" =
    isCurrentlyOperational ? "Inoperative" : "Operative";
  // ... rest unchanged ...
};
```

### Franchisee charger detail page

Locate the parallel toggle (probably `frontend/app/franchisee/chargers/[id]/page.tsx` based on file naming conventions) and apply the same change. The franchisee endpoint takes a boolean (`?available=true|false`); map `availability === "Operative"` to `true`.

### Comment cleanup

The existing comment in `page.tsx:104-110` should be updated to reflect the new logic:

```typescript
// Toggle reflects ADMIN-SET availability intent (Charger.availability),
// not what the charger currently reports (Charger.latest_status). Per
// OCPP 1.6 + ADR 0008, these are orthogonal: a Faulted charger can be
// admin-set Operative, a Charging charger can be admin-set Inoperative
// (will transition after the session ends per OCPP Scheduled semantics).
```

## Verification

1. **Local dev build** (per `feedback_full_build_required` memory — `tsc --noEmit` is NOT sufficient):

   ```bash
   cd frontend && npm run build
   ```

   Expected: build completes without new warnings or errors. Pay attention to `@typescript-eslint/no-unused-vars` and `react/no-unescaped-entities` — both are full-build-only enforcers.

2. **Manual browser test** (against staging once deployed):
   - Navigate to `/admin/chargers`
   - Find a charger whose `latest_status` is something OTHER than `Available` (e.g., `Preparing` or `Unavailable`)
   - The toggle should now reflect the `availability` field, not the status pill
   - Click the toggle → backend persists new value → re-fetch → toggle flips correctly
   - Repeat with a charger that is currently `Faulted` (or simulate via DB): toggle should still be operable and reflect admin intent independently of fault state

3. **OCPP simulator E2E** (optional, but the right way to fully verify):
   - Start simulator
   - Toggle the simulated charger to Inoperative via admin UI
   - Confirm `availability=Inoperative` in DB
   - Toggle back to Operative
   - Confirm `availability=Operative` regardless of what `latest_status` says

## Definition of done

- `Charger` interface includes `availability: "Operative" | "Inoperative"`
- All call sites of `getAvailabilityToggleState` read the new field
- Both admin and franchisee toggles work end-to-end against a real charger
- `npm run build` in `frontend/` succeeds with no new warnings
- PR merged to `develop`
- Staging deploy verified — the original bug reproduction (toggle two clicks both send same `type`) is gone
