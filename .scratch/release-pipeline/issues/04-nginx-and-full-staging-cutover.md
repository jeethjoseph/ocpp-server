# nginx in CI + full staging cutover

Status: ready-for-agent

Spec: [ADR 0019](../../../docs/adr/0019-release-pipeline-build-off-host.md) — Images, Consequences sections.

## What to build

Add the last built image (`nginx`) to the pipeline and complete the **staging** cutover: a full staging release now pulls all three CI-built images and runs **zero `docker build` on the host**.

- GHA workflow builds `ocpp-nginx:sha` (nginx base + baked config; no secrets) and pushes to ECR.
- Staging override references all three images (`backend`, `frontend`, `nginx`) by SHA.
- The on-host `--build` release path is retired for staging: `staging-deploy` / `staging-rebuild` are deprecated in favour of `make staging-release` (alias prints a deprecation notice pointing at the new target).
- Upstream `postgres`/`redis`/`certbot` remain pulled-by-tag (unbuilt) — unchanged.

## Acceptance criteria

- [ ] `ocpp-nginx:sha-<short>` is built and pushed by CI; the staging nginx service pulls it.
- [ ] A full `make staging-release` pulls all three images and runs no `docker build` anywhere on the host.
- [ ] `staging-deploy` / `staging-rebuild` (build-on-host) are deprecated — invoking them prints a notice pointing to `staging-release`.
- [ ] Upstream `postgres`/`redis`/`certbot` are still pulled by their version tags (not built).
- [ ] Local `docker-compose.yml` remains build-based for dev.

## Blocked by

- [03 — Frontend in CI: build args, secrets, Dockerfile ARG wiring](03-frontend-in-ci-args-secrets.md)
