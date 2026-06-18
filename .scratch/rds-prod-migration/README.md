# RDS production migration

This folder is the **plan**, not the implementation. The prod migration is **not active** — it's gated on the staging migration's 14-day validation window closing cleanly (started 2026-05-27, validates through ~2026-06-10).

## When this becomes real

Activate this project only when **all** of these are true:

- [ ] Staging RDS validation window has closed with all decommission triggers green
- [ ] `.scratch/rds-staging-migration/issues/07-decommission-docker-postgres.md` is `completed` — i.e., Docker postgres on staging is gone and we've lived without the rollback safety net for at least a few days
- [ ] No deferred follow-ups from staging that we're carrying forward

## Reading order

1. `PRD.md` — the full plan, including the staging lessons applied as pre-cutover hardening
2. `.scratch/rds-staging-migration/PRD.md` "Lessons learned" section — the post-mortem this plan inherits from
3. `.scratch/rds-staging-migration/issues/05-cutover-runbook.md` — the staging cutover script that this prod cutover mirrors

## Status

`needs-triage` until staging decommission completes. Do not promote without re-reading the pre-cutover hardening section in `PRD.md`.
