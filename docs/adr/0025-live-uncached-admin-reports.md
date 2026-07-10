# Admin analytical reports are computed live on every request — no snapshot table, no server cache

The **Churn Report** (and the `/admin/reports` surface generally) recomputes its aggregation against Postgres on each fetch. There is **no** materialized snapshot, **no** `report_snapshot` table, and **no** Redis blob. The "don't recompute until the user asks" requirement is satisfied entirely on the client: TanStack Query holds the result with `staleTime: Infinity` and a **Refresh** button calls `refetch()`. The "last refreshed X ago" label is the client's `dataUpdatedAt`, not a persisted server timestamp.

## Context

The original ask was explicitly a *cached* report — "not refreshed until the user refreshes it… last refreshed X ago… so as to not bog down the DB." That framing assumes the aggregation is expensive enough that running it per page-load threatens the shared RDS instance (a single-AZ `db.t4g.small` that also serves live OCPP traffic — the same box implicated in the memory-pressure incidents).

Before committing to a snapshot, the cohort query was measured on prod (`EXPLAIN (ANALYZE, BUFFERS)`, 2026-07-10):

- `qr_payment`: **462 rows, 455 successful, 1 MB table.**
- Cohort aggregation: **1.86 ms execution time, 107 shared-buffer hits, zero disk reads** — a fully in-memory sequential scan.
- Projected growth at ~130 payments/month: ~5,000 rows in three years → still a sub-10 ms scan.

The premise didn't hold. At this scale a snapshot is caching a 2 ms query behind a table, a migration, a refresh endpoint, and invalidation semantics — pure overhead. Separately, `staleTime: Infinity` + `dataUpdatedAt` on the client already delivers *both* things the user actually wanted (manual refresh, a "last refreshed" label) with no server state at all.

## Decision

Compute live; do not cache.

- **Endpoint** `GET /api/admin/reports/qr-churn` runs the aggregation as raw SQL and returns a plain dict (money/dates as strings, per the `admin_invoices_summary` convention). `Depends(require_admin())`.
- **Both queries run in one bounded, consistent read.** They execute inside a single `in_transaction` set to `REPEATABLE READ` (so the cohort grid and the summary are computed from the same MVCC snapshot and cannot disagree) with `SET LOCAL statement_timeout = 5000` (a scale guard-rail — the scan is unbounded, so cap it rather than let it compete unboundedly with live OCPP traffic if the table ever grows). A `Custom/Reports/QrChurn/DurationMs` metric + `Request` counter are emitted so the "revisit at ~100 ms" threshold below is actually observable.
- **Cohort periods are IST periods.** `created_at` is stored UTC, but this is an India-only business, so a period boundary must be an IST midnight: `date_trunc(grain, created_at AT TIME ZONE 'Asia/Kolkata')`. Without the conversion, a charge just after IST-midnight buckets into the prior UTC week/month (weekly is hit ~7× more often than monthly). Latent at low volume but wrong, and inconsistent with the CLAUDE.md store-UTC/present-IST rule.
- **Client owns the refresh contract.** `staleTime: Infinity` means the query never refetches on its own — not on remount, refocus, or reconnect. Only the explicit **Refresh** button (`refetch()`) re-hits the endpoint. `dataUpdatedAt` renders "last refreshed X ago" (relative label; absolute **IST** on hover, per the UTC-store/IST-present rule).
- **Consequence of client-owned staleness, stated plainly:** "last refreshed" is **per-viewer**, and two admins can see different numbers if data changed between their fetches. This is accepted — these are triage/insight reports, not a shared source of truth. A team-wide frozen snapshot was explicitly *not* chosen.

## Consequences

- **Zero new persistence.** No table, no Aerich migration, no Redis key, no invalidation. The report is a pure function of the current DB state at fetch time.
- **Numbers are always live at fetch.** No staleness-vs-truth gap to reason about; the only "staleness" is however long ago the viewer last clicked Refresh, which the label makes explicit.
- **This is a scale-bound decision, and the bound is recorded.** The cohort query is an **unbounded sequential scan of `qr_payment`** — cheap only because the table is tiny and fully cached. Revisit if `qr_payment` grows past ~100k rows or the measured query time exceeds ~100 ms, whichever comes first. At that point the fix is a bounded/indexed query surface (per [[adr-0014-logs-console-bounded-query-surface]]) first, and only then a snapshot if genuinely needed.
- **Future readers: do not add a cache here reflexively.** The absence of one is deliberate and measured. Adding a `report_snapshot` table is easy and reversible *later*; doing it now would be cargo-culted premature optimization. If you add one, do it for a *product* reason (a shared, team-wide frozen snapshot) — not for DB cost, which this ADR has already ruled out at current scale.

## Considered alternatives

- **Durable `report_snapshot` DB table** (one row per report, `computed_at`/`computed_by`, upserted on a refresh endpoint). Rejected at current scale: it caches a 2 ms query behind real machinery. Its *only* genuine advantage is a **shared, team-wide** "last refreshed" and stable numbers across admins — a product property the team did not ask for. Reconsider only if that shared-snapshot semantics becomes a requirement.
- **Redis blob with no TTL** (`report_snapshot:` prefix). Rejected: leans on infra that is explicitly optional/fallback-tolerant for what would be durable state; a `FLUSHALL`/eviction silently blanks the report. Wrong tool, and unnecessary given the measured cost.
- **Redis blob with a short TTL.** Rejected: reintroduces a cache to protect against a cost that doesn't exist, and a TTL that silently expires contradicts the "only refresh when I ask" contract.
- **In-process periodic recompute loop** (the `firmware_update_service` pattern). Rejected: spends background DB work on a report nobody may be looking at, and still needs somewhere to store the result. The client-refresh model does strictly less work.
