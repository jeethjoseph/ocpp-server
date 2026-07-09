# Tracer bullet: backend built in CI → ECR → staging release

Status: ready-for-agent

Spec: [ADR 0019](../../../docs/adr/0019-release-pipeline-build-off-host.md) — Decision, Artifact identity, Release trigger sections.

## What to build

The thinnest end-to-end proof of the whole pipeline, on the one service that needs **zero build secrets** (backend). A push to `develop` builds the backend image in GitHub Actions, pushes it SHA-tagged to ECR, and a human releases it to **staging** by pulling — the host runs no `docker build`.

- GHA workflow: on push to `develop`, build the backend image, tag `ocpp-backend:sha-<short>` (plus a moving `:staging` pointer), push to ECR (auth via the OIDC role from #01).
- Staging compose override: the staging `backend` service uses `image: <ECR>/ocpp-backend:<sha>` instead of `build:`.
- `make staging-release`: `pull` + `up -d` for the backend (migration step comes in #05). No build on the host.
- Local `docker-compose.yml` backend stays `build:`-based — dev is unaffected.

This deliberately isolates the OIDC/ECR/release-flow plumbing from the frontend secret/ARG complexity (which lands in #03).

## Acceptance criteria

- [ ] Pushing to `develop` triggers a GHA build of the backend image, tagged `ocpp-backend:sha-<short>` and pushed to ECR using the OIDC role (no static keys).
- [ ] The staging override makes the backend service pull `image:` rather than build.
- [ ] `make staging-release` pulls the SHA image and recreates the staging backend from it; `docker build` runs nowhere on the host.
- [ ] The running staging backend reports the released git SHA (e.g. via `GIT_COMMIT`/health/version).
- [ ] The backend build requires no GitHub Actions variables or secrets (confirms the no-secret path).
- [ ] Local dev (`docker-compose.yml`) still builds the backend from source unchanged.

## Blocked by

- [01 — AWS foundation: ECR repos + OIDC trust + scoped push role](01-aws-foundation-ecr-oidc-role.md)
