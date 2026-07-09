# Migration step in the release flow + expand/contract checklist

Status: ready-for-agent

Spec: [ADR 0019](../../../docs/adr/0019-release-pipeline-build-off-host.md) — Migration ordering section.

## What to build

Fold the schema migration into the release flow in the safe order, and document the discipline that makes SHA-image rollback safe against a forward-only schema.

- **Remove `aerich upgrade` from `backend/docker-entrypoint.sh`.** Today (verified 2026-06-30) the entrypoint runs `aerich upgrade` on every boot *and* hardcodes `exec uvicorn`, ignoring any passed command — which is why `docker compose run backend aerich upgrade` silently starts a server instead of migrating. The entrypoint must become **wait-for-DB → `exec "$@"`** (default command = uvicorn), so it (a) no longer auto-migrates and (b) honors a passed command.
- `make {env}-release` runs `aerich upgrade` from the **new** image as a one-shot (`docker compose run --rm --no-deps backend aerich upgrade`, not touching the serving container) **before** `up -d` swaps serving traffic.
- **Behavior-change guard:** once auto-migrate is removed, a release with a pending migration that *skips* the migrate step would leave the schema behind silently. The release flow/runbook must make the migrate step unskippable (or fail loud if the running code is ahead of the schema).
- Document, in the release runbook: the **expand/contract** rule (every migration must be backward-compatible with the currently-running image; destructive/tightening changes split across two releases — expand then contract); the pre-release checklist *"contains migration? expand-only? blocking?"*; rollback = retag prior SHA + `up -d` (schema forward-only; RDS PITR/snapshot for disaster, never `aerich downgrade` on prod); blocking DDL (e.g. `CREATE INDEX CONCURRENTLY`, the `{env}-create-log-indexes` pattern) run **out-of-band before** the release.

## Acceptance criteria

- [ ] `backend/docker-entrypoint.sh` no longer runs `aerich upgrade`; it waits for the DB then `exec "$@"` (default command = the uvicorn invocation), so a passed command (`aerich upgrade`) is honored.
- [ ] `docker compose run --rm --no-deps backend aerich upgrade` actually runs a migration (not a server) against the target DB.
- [ ] `make {env}-release` runs `aerich upgrade` from the new image as a one-shot before swapping serving containers.
- [ ] A release containing an expand migration applies it before the swap; a release with no new migration is a safe no-op (idempotent).
- [ ] A release with a pending migration cannot silently skip the migrate step (it's part of `{env}-release`, or the app refuses to serve / alerts when code is ahead of schema).
- [ ] Runbook documents: expand/contract two-release split for destructive changes; the "contains migration? expand-only? blocking?" checklist; retag-to-rollback with the forward-only-schema/PITR caveat; out-of-band `CONCURRENTLY` for blocking DDL.

## Blocked by

- [02 — Tracer bullet: backend built in CI → ECR → staging release](02-tracer-backend-ci-to-staging.md)
