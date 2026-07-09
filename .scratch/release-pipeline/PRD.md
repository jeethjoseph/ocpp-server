# Release pipeline — build off the live host

Spec: [ADR 0019 — Release pipeline: build images off the live host](../../docs/adr/0019-release-pipeline-build-off-host.md)

Move Docker image builds off the live EC2 host (root cause of the 2026-06-30 prod memory-thrash outage) to **GitHub Actions → Amazon ECR → release on EC2 via SSM** (pull + one-shot migrate + up, never `--build` on the host).

Each issue is a thin end-to-end slice of the pipeline (auth → build → registry → release), traced first on the simplest service then thickened.

| # | Slice | Type | Blocked by |
|---|-------|------|-----------|
| 01 | AWS foundation: ECR repos + OIDC trust + scoped push role | HITL | — |
| 02 | Tracer bullet: backend built in CI → ECR → staging release | AFK | 01 |
| 03 | Frontend in CI: build args, secrets, Dockerfile ARG wiring | AFK | 02 |
| 04 | nginx in CI + full staging cutover | AFK | 03 |
| 05 | Migration step in the release flow + expand/contract checklist | AFK | 02 |
| 06 | Prod cutover: `deploy`-branch build, prod override, `make prod-release`, rollback runbook | HITL | 04, 05 |

## Not in this feature (separate / already tracked)

- **Postgres decommission** — prerequisite cleanup, tracked in `.scratch/rds-staging-migration/issues/07-decommission-docker-postgres.md` (both RDS validation windows now closed).
- **Interim swap** on prod — operational band-aid to unstick the currently half-deployed release; not part of the pipeline.
