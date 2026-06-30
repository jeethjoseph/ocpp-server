# ADR: log-table query guard + indexing

Status: done
Type: HITL
Resolution: ADR landed as docs/adr/0014-logs-console-bounded-query-surface.md (2026-06-23)

## What to build

Write a short ADR (next number in `docs/adr/`) recording the decision to make the fleet-wide **Logs Console** safe to query against the `log` table.

The `log` table is dominated by MeterValues/Heartbeat and currently has **no indexes** beyond the `id` PK. Growth is already capped at ~90 days by the `DataRetentionService` cleanup job (`RETENTION_DAYS`, default 90) — but 90 days of fleet-wide high-frequency traffic is still far too much for an unindexed fleet-wide seq scan. The decision: rather than allow free-form querying (or rely on the retention cap alone), we guard the query surface with (a) an always-bounded date window defaulting to the last 24h, (b) a row `limit` cap, and (c) targeted indexes `(charge_point_id, timestamp)` and `(message_type, timestamp)`.

Capture the trade-off: why a bounded window + targeted indexes over the alternatives (naked unindexed querying, relying on the 90-day retention cap alone, archival/tiering, a dedicated analytics store), and the consequence that there is deliberately no unbounded fleet-wide query. Note the bonus that an aligned time index also speeds the retention job's own `created_at__lt` batched deletes.

This documents a decision already locked in the grill-with-docs session; it does not re-open it.

## Acceptance criteria

- [ ] New ADR file added under `docs/adr/` with the next sequential number
- [ ] States the context (unindexed, MeterValues-dominated `log` table; growth already capped at ~90d by `DataRetentionService`, which is not enough on its own)
- [ ] States the decision (bounded default window + limit + the two indexes)
- [ ] Lists rejected alternatives (incl. relying on the 90d retention cap alone) and the consequence (no unbounded fleet-wide query)
- [ ] Cross-links the **Logs Console** and **OCPP Action** terms in `CONTEXT.md`

## Blocked by

None - can start immediately.
