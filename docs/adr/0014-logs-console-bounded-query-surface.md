# The fleet-wide Logs Console queries the `log` table through a bounded, indexed surface — never an unbounded scan

The **Logs Console** (`/admin/logs`) lets an admin query **OCPP message log** rows across all chargers. Rather than expose the `log` table to free-form querying, the query surface is deliberately constrained: the date range is **always bounded and defaults to the last 24h**, a row `limit` caps every response, and two composite indexes — `(charge_point_id, timestamp)` and `(message_type, timestamp)` — back the only two server-side filter dimensions (**Charger** and **OCPP Action**). There is intentionally no "all chargers / all actions, widest range" path that runs unindexed.

## Context

The `log` table (`OCPPLog`) is **dominated by MeterValues and Heartbeat** — the two highest-frequency OCPP actions, emitted continuously by every charger whether or not a session is active. Before this work the table carried **no indexes beyond the `id` primary key**.

Growth is *not* unbounded: the `DataRetentionService` background job batch-deletes `OCPPLog` rows older than `RETENTION_DAYS` (default **90 days**) every `CLEANUP_INTERVAL_HOURS` (default 24h). So the table holds a rolling ~90-day window, not all history. The retention cap alone, however, does **not** make the table cheap to query — 90 days of fleet-wide, MeterValues-saturated traffic is still a large dataset, and an unindexed fleet-wide query is a full sequential scan over all of it.

The per-charger embedded viewer got away with the missing indexes because the implicit `charge_point_id` filter plus a small fleet kept each (seq-scan) query bounded in practice. Promoting logs to a fleet-wide page removes that implicit narrowing.

## Decision

Constrain the query surface and index the two dimensions it filters on:

- **Always-bounded date window**, defaulting to the **last 24h**. Widenable, but the meaningful ceiling is the ~90-day retention window — there is no "all time" because there is no all-time data.
- **Row `limit` cap** on every response, with `has_more` / `total` surfaced honestly so truncation is visible rather than silent.
- **Targeted indexes** `(charge_point_id, timestamp)` and `(message_type, timestamp)`, matching the two server-side filter dimensions. Direction and status refine in memory over the already-narrowed, fetched window and need no index.

## Consequences

- **No unbounded scan from the UI.** An admin chasing an older event widens the date range (still limit-capped, still inside ~90 days) or filters by charger/action. A deliberate guard-rail, not a missing feature.
- **The indexes cost write amplification and disk** on a high-write table. Accepted: two composite indexes on an append-mostly table is modest next to the read-safety they buy.
- **The retention cleanup benefits too.** `DataRetentionService` deletes via `created_at__lt` in batches — itself an unindexed scan today. Aligning the time index with the column the deletes filter on (or accepting that `created_at` ≈ `timestamp`, both `auto_now_add`) lets the cleanup job use an index instead of a seq scan. The slice that adds the indexes should confirm the cleanup query and the Console query order on the *same* indexed column.
- **Retention policy is unchanged.** This ADR governs *query safety*, not *growth*; the 90-day window is owned by `DataRetentionService` and `RETENTION_DAYS`.

## Considered alternatives

- **Leave the table unindexed and allow free-form queries.** Rejected: a full seq scan over 90 days of MeterValues-dominated traffic is a latent outage the moment the page ships to a real fleet.
- **Rely on the 90-day retention cap alone (no window, no indexes).** Rejected: retention bounds *growth*, not *per-query cost*. Ninety days of fleet-wide high-frequency traffic is still far too much to seq-scan on an admin page load.
- **Archival / retention tiering (move old rows to cold storage).** Rejected as redundant: `DataRetentionService` already deletes beyond 90 days, so there is no long tail to tier. Revisit only if the retention window itself ever needs to grow dramatically.
- **A dedicated analytics/observability store.** Rejected as disproportionate: the need is admin triage over recent protocol traffic, not analytics. The `log` table within its retention window is the source of truth; duplicating it earns nothing here.
- **A hard gate requiring a charger or action before any query runs.** Rejected: clunky UX and asymmetric with the "All / All" default. The bounded window + limit + indexes make the unfiltered case safe without forcing a selection.
