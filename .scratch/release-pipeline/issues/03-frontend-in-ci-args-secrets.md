# Frontend in CI: build args, secrets, Dockerfile ARG wiring

Status: ready-for-agent

Spec: [ADR 0019](../../../docs/adr/0019-release-pipeline-build-off-host.md) — Secrets model, Images sections.

## What to build

Add the **frontend** image to the pipeline — the memory-heavy, secret-consuming build that caused the outage. CI builds it on a 16 GB runner with the build inputs supplied from GitHub, uploads source maps to Sentry, and pushes `ocpp-frontend:sha`; staging pulls it.

- Configure GitHub **Actions Variables** for the 13 public build values (the `NEXT_PUBLIC_*` group + `SENTRY_ORG` + `SENTRY_PROJECT`) and **one Actions Secret**: `SENTRY_AUTH_TOKEN`.
- Verify `frontend/Dockerfile` declares an `ARG` for **every** build value CI passes (the CLAUDE.md trap — a missing `ARG` is silently dropped); `NEXT_PUBLIC_*` also `ENV` in the builder; `SENTRY_AUTH_TOKEN` injected **inline on the build `RUN`** so it never lands in an image layer.
- Sentry source-map upload runs during the CI build.
- Staging override pulls `ocpp-frontend:<sha>`; remove `SENTRY_AUTH_TOKEN` from the staging host `.env` (host no longer builds the frontend).

## Acceptance criteria

- [ ] GitHub Actions has the 13 variables + `SENTRY_AUTH_TOKEN` secret configured (one-time human setup).
- [ ] `frontend/Dockerfile` has a matching `ARG` for every CI-passed build value; `SENTRY_AUTH_TOKEN` is inline on the `RUN`, not a persisted layer.
- [ ] The CI build uploads source maps (build log shows "Uploaded N sourcemaps"; a Sentry release with artifacts appears).
- [ ] `ocpp-frontend:sha-<short>` is pushed to ECR; the staging frontend service pulls it; no on-host frontend build runs.
- [ ] A known `NEXT_PUBLIC_*` value is verifiably baked into the served bundle.
- [ ] `SENTRY_AUTH_TOKEN` is removed from the staging host `.env`.

## Blocked by

- [02 — Tracer bullet: backend built in CI → ECR → staging release](02-tracer-backend-ci-to-staging.md)
