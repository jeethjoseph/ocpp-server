# 01 — ADR: Reports framework + time-bucketing aggregation pattern

Status: ready-for-human

## What to build

Write a single ADR (next number in `docs/adr/`) that records the architectural decisions behind the new admin **Reports** feature, so downstream slices have a documented contract to build against.

The ADR must capture:

- **Reports framework**: a top-level admin section (`/admin/reports`) that hosts multiple *subreports* behind a tab strip. Temperature ships first; Energy/kWh, Signal quality (RSSI/BER), and Sessions/revenue are planned subreports the framework must accommodate later. Record why this is a dedicated reporting surface rather than widening the live `ModemTemperatureCard` (aggregated/historical analysis vs. live status).
- **Time-bucketing aggregation pattern**: this is a *new* pattern for the codebase — no existing `date_trunc`/time-bucketing precedent exists (current aggregation is `.annotate(Sum/Count)` + `.group_by()` on plain columns). Record the decision to bucket rows by time via parameterized raw SQL `date_trunc` (guarded against injection), returning `min/avg/max/sample_count` per bucket. Note the auto-granularity rule: **hourly for ranges ≤ 7 days, daily beyond**.
- **90-day retention cap**: report ranges are hard-capped at 90 days because `data_retention_service` deletes `signal_quality` rows older than 90 days. Ranges beyond the floor are disabled in the UI rather than silently returning empty.

## Acceptance criteria

- [ ] New ADR file added under `docs/adr/` with the next sequential number, following the existing ADR format
- [ ] Documents the Reports framework + subreport-tab structure and the list of planned subreports
- [ ] Documents the raw-SQL `date_trunc` bucketing decision, the hourly/daily auto-granularity rule, and why the ORM `.annotate` precedent is insufficient
- [ ] Documents the 90-day hard cap and its link to `data_retention_service`
- [ ] Referenced by the aggregation endpoint slice (02) as the source of truth

## Blocked by

- None - can start immediately
