# Partition `log` by month

Status: needs-triage

> **Not scheduled.** Filed so the option is on the record with its evidence.
> Do [[01-make-the-failure-legible]] and [[02-autovacuum-tuning-on-log]] first
> and see whether the problem survives them.

## What to build

Convert `log` to a range-partitioned table on `timestamp`, one partition per
month, and replace the retention delete with `DROP PARTITION`.

## Why it is the structurally correct answer

`log` is an append-only, high-churn, time-ordered table: 14.6M rows, ~7.2 GB,
~162,000 inserts/day, and a 90-day retention window. Deleting a day's worth
currently means ~162,000 row deletes across **four** indexes, generating dead
tuples that then need vacuuming, which is the cycle that produces the timeout.

Dropping a partition is a metadata operation. It is effectively instant, takes
no row locks on live data, produces **zero** dead tuples, and removes the bloat
cycle rather than managing it. Retention stops being a workload.

## Why it is not scheduled

- It is a real migration on a 7 GB table on both registers, needing a careful
  cutover (create partitioned parent, attach existing data, swap).
- Tickets 01 and 02 are cheap and may reduce the problem to nothing. Doing the
  large structural fix first would be solving a problem we have not yet failed
  to solve cheaply.
- The Logs Console queries this table ([[adr-0014-logs-console-bounded-query-surface]]);
  partition pruning should help those, but the query patterns need checking
  against the partition key before committing.

## What to decide

Whether 90-day retention on a table this size is better served by partitions or
by tuned autovacuum. If ingest grows materially past ~162k/day, partitioning
stops being optional.

## Acceptance criteria

- [ ] A decision recorded, with the `n_dead_tup` and timeout behaviour observed after tickets 01 and 02.
- [ ] If proceeding: an ADR covering the partition key, the retention mechanism change, and the cutover.

## Blocked by

- [[01-make-the-failure-legible]]
- [[02-autovacuum-tuning-on-log]]
