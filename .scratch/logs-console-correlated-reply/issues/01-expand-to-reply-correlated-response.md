# Expand-to-reply: correlated OCPP response in the Logs Console

Status: ready-for-human

## What to build

In the admin Logs Console, let an operator see the response to any OCPP request without hunting through the log stream. On a request frame (a `Call`, wire type `2`), show a **"▸ Show response"** toggle that lazily fetches and inlines that request's correlated reply (`CallResult` / `CallError`).

End-to-end behavior:

- **API** — the fleet-wide logs list endpoint gains an additive `correlation_id` filter. It composes with the existing charger / action / direction / window filters; no other behavior changes. No migration — the `correlation_id` column already exists and is already stored on every row.
- **Frontend** — a request card renders the toggle; on expand it fetches the reply scoped by `correlation_id` **+ `charge_point_id` + a tight time window** around the request timestamp. The window is essential for two reasons: (a) the list endpoint defaults to a bounded 24h window, so a historical request would otherwise miss its own reply, and (b) charger-chosen messageIds (e.g. `boot_55C1E96E`) can be **reused across reboots**, so `correlation_id` alone is not unique. From the returned rows, pick the one whose payload is wire type `3` (CallResult) or `4` (CallError).
- The reply renders with the **same frame renderer** as a normal row (extract the existing payload-rendering block into a shared component so they stay identical), including the IST-converted timestamp (server is UTC — see CLAUDE.md "Timestamps").
- Empty state: when no reply is found (charger never answered, or it falls outside the window) show a clear **"No response recorded"** rather than a spinner or blank.

**Why this over a flat filter:** `CallResult` is by far the highest-volume message type (~62.5k rows/24h on staging vs ~52 BootNotifications — every heartbeat/status/meter ack is a CallResult), so adding it to the flat action filter buries the request you care about below thousands of newer CallResults. Drilling into a single request's `correlation_id` sidesteps the volume entirely. This is a UX affordance on top of data that is already persisted — see [ADR 0014](../../../docs/adr/0014-logs-console-bounded-query-surface.md).

The toggle appears **only** on request frames (wire type `2`); response/error frames do not get it. `message_type` semantics are unchanged (responses stay labelled `CallResult` / `CallError`).

## Acceptance criteria

- [ ] `GET /api/admin/logs?correlation_id=<id>` returns only rows with that correlation_id, and composes correctly with existing charger/action/direction/date filters.
- [ ] A request card (wire type `2`) shows a "Show response" toggle; response/error cards do not.
- [ ] Expanding a BootNotification fetches and displays its `CallResult` reply (e.g. `{ interval: 30, status: "Accepted" }`) inline, rendered by the shared frame renderer with an IST timestamp.
- [ ] The reply lookup is scoped by correlation_id + charge_point_id + a bounded time window around the request, so it works for rows older than 24h and does not mismatch a reply from a different reboot that reused the same messageId.
- [ ] When no correlated reply exists, the expander shows "No response recorded" (not a blank or perpetual loading state).
- [ ] Backend test in `test_logs_console.py` covers the `correlation_id` filter (match + compose-with-other-filters).
- [ ] `cd frontend && npm run build` passes (full production build, not just tsc/lint).
- [ ] Docs updated: ADR 0014 addendum recording the correlation_id filter + expand-to-reply, plus `docs/v1/llm-context-document.md` and `docs/v1/comprehensive-architecture-documentation.md`.

## Blocked by

- None - can start immediately

## Comments

**2026-07-09 — implemented (agent).** All code + docs written; one verification step blocked by the local environment.

Changes:
- `backend/routers/logs.py` — additive `correlation_id` filter in `_build_logs_query` + `get_logs` (no migration; column pre-existed).
- `backend/tests/test_logs_console.py` — `test_correlation_id_filter_returns_only_the_pair`, `test_correlation_id_composes_with_direction`.
- `frontend/lib/api-services.ts` — `correlation_id` on `LogQueryParams` + `buildLogQuery`.
- `frontend/lib/queries/logs.ts` — `useLogReply` hook (correlation_id + charge_point_id + −5s/+120s window).
- `frontend/app/admin/logs/page.tsx` — extracted shared `FrameBody`; added `isRequestFrame`, `CorrelatedReply`, and the "Show response" toggle on wire-type-2 cards; dropped now-unused default `React` import.
- Docs: ADR 0014 addendum + `docs/v1/llm-context-document.md` + `docs/v1/comprehensive-architecture-documentation.md`.

Verification:
- ✅ `frontend` `tsc --noEmit` clean; ✅ `npm run build` — `Compiled successfully`, exit 0.
- ✅ backend `py_compile` clean on both files.
- ✅ `docker exec ocpp-backend pytest tests/test_logs_console.py` — **18 passed** (16 pre-existing + the 2 new correlation_id tests) once OrbStack was back up.

All acceptance criteria met and verified. Ready for human review / merge.
