# Tune autovacuum for the `log` table

Status: ready-for-human

## What to build

A per-table autovacuum override on `log`, on both RDS instances.

## Why

The batch-delete timeout in [[01-make-the-failure-legible]] is a symptom; this
is the driver. Measured on production 2026-09-09:

| Metric | Value |
|---|---|
| `n_live_tup` | 14,580,330 |
| `n_dead_tup` | **1,261,568** |
| `last_autovacuum` | **2026-08-28** — twelve days earlier |
| Deletes per day | ~162,000 |

Postgres's default `autovacuum_vacuum_scale_factor` is 0.2, so autovacuum will
not trigger on this table until dead tuples reach roughly 20% of 14.6M ≈ **2.9
million rows**. At ~162k deletes/day that is an eighteen-day cycle, and between
runs the index accumulates debris that every retention `SELECT` must scan past.
That is what makes each successive batch slower until one crosses the 30s
`command_timeout`.

A scale factor appropriate to a table this size:

```sql
ALTER TABLE log SET (autovacuum_vacuum_scale_factor = 0.02,
                     autovacuum_analyze_scale_factor = 0.02);
```

That triggers at ~290k dead tuples — roughly every other day — keeping the index
lean. It very likely makes the retention timeout disappear on its own.

`ready-for-human` because it is a database change on both RDS instances, and
because the right scale factor is a judgement about vacuum load on a
`db.t4g.small` versus index bloat. Worth watching `n_dead_tup` for a week after.

## Acceptance criteria

- [ ] Override applied to `log` on staging, and `n_dead_tup` observed falling within 48h.
- [ ] Same applied to production once staging looks right.
- [ ] Autovacuum load on the instance checked — CPU and IO should not materially rise on a t4g.small.
- [ ] Recorded in `docs/runbooks/log-retention-timeout.md` once settled.

## Blocked by

None, but do [[01-make-the-failure-legible]] first — otherwise there is no clean signal to tell whether this worked.
