# Debounce admin charger-list search & hold the list during refetch

Status: ready-for-agent

## What to build

Typing in the search box on the `/admin/chargers` list page currently lags and visibly "refreshes the whole page" on every keystroke — the list unmounts to a loading/empty state while a request is in flight, then repopulates.

Make the search feel instant and stable: the list should stay on screen (showing the previous results) while a new search request resolves, and the server should not be hit on every single character.

Root cause (for context, not prescription):
- The search term is fed straight into the chargers query with no debounce, so one server request fires per keystroke.
- The chargers query keys its cache on the full params object, has an aggressive ~3s `refetchInterval`, and keeps no previous data — so each keystroke is a brand-new cache entry with nothing cached, which collapses the list to a loading state until the request returns.

The existing `ChargerCombobox` (used on the logs page) already debounces its server query at ~250ms — mirror that behavior here so the two charger searches are consistent.

## Acceptance criteria

- [ ] Typing in the `/admin/chargers` search field no longer triggers a server request on every keystroke — requests are debounced (~250ms after typing stops)
- [ ] The charger list does NOT blank out / drop to a loading state while a search request is in flight — the previous results remain visible until the new ones arrive (`placeholderData: keepPreviousData` or equivalent)
- [ ] The 3s auto-refresh does not cause the list to flicker or reset the user's scroll/focus while they are actively typing a search
- [ ] Behavior is consistent with the `ChargerCombobox` search on the logs page
- [ ] No regression to status/station filters or pagination on the chargers list
- [ ] `cd frontend && npm run build` passes (per project rule — full production build, not just tsc/lint)

## Blocked by

None - can start immediately
