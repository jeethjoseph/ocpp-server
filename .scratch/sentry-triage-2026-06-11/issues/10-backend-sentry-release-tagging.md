# Tag backend Sentry events with the real release instead of "dev"

Status: ready-for-agent

Observability gap surfaced during the 2026-06-11 Sentry triage: every backend event in this batch carried `release: dev`, while the frontend correctly reported `release: production-2026-06-08T10-04-28`. Without a real release on backend events, regression attribution ("which deploy introduced this?"), regression resolution, and release-health in Sentry are all unusable for `ocpp-backend`.

## What to build

`SentryHelper` initializes the SDK with `release=os.getenv("GIT_COMMIT", "dev")`. `GIT_COMMIT` is never populated in the backend container, so the release always falls back to the literal `dev` — the documented env-var trap (a var on disk / in `.env` does not reach the container unless it is in the `backend.environment:` block of the compose files, and here it isn't passed in at all).

Wire a real release identifier into the backend container so Sentry tags events with the deployed version (git commit SHA or a release tag), consistent with how the frontend already does it. This means: supply the value at deploy/build time, pass it through `backend.environment:` in all three compose files per the env-var checklist, and keep a sensible fallback so local dev still works.

Follow the env-var checklist in CLAUDE.md (value source → `.env*.example` → `backend.environment:` in `docker-compose.yml`, `.staging.yml`, `.prod.yml`), and have `main.py` startup log a warning if the release resolves to the `dev` fallback in staging/prod so a misconfigured deploy fails loud.

## Acceptance criteria

- [ ] Backend Sentry events in staging/prod are tagged with the deployed git SHA (or release tag), not `dev`.
- [ ] `GIT_COMMIT` (or equivalent) is present in `backend.environment:` of all three compose files with a local-dev fallback.
- [ ] The release value is populated at deploy time by the deploy mechanism (documented in the issue / Makefile).
- [ ] Startup logs a warning when the release resolves to the `dev` fallback in a non-dev environment.
- [ ] Verified locally: `docker exec ocpp-backend env | grep` the release var shows the expected value; a test event in Sentry shows the correct release.

## Blocked by

None - can start immediately.

## Comments

**Implemented 2026-06-11.** `monitoring_service.py` release now resolves `SENTRY_RELEASE` → `GIT_COMMIT` → `{env}-{startup-timestamp}` (mirrors `next.config.ts`), with a startup warning when it falls back in a non-dev env. `GIT_COMMIT`/`SENTRY_RELEASE` added to `backend.environment:` in all three compose files and documented in `.env.{staging,prod}.example`. `make staging-rebuild` / `make prod-rebuild` now export `GIT_COMMIT=$(git rev-parse --short HEAD)` so compose stamps it in. Runtime-verified: with `GIT_COMMIT=abc1234` → release `abc1234`; unset → `staging-<ts>` + warning.
