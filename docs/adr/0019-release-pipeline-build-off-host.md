# Release pipeline: build images off the live host, ship pre-built images per environment

**Status:** accepted (2026-06-30)

## Terminology

- **Release** — shipping a new application *image* to an environment (staging/prod). This ADR's subject.
- **Deploy** — reserved for the firmware→charger product action (see `CONTEXT.md` "Firmware deployment"). A **Release** is *not* a Deploy. The legacy `prod-deploy` / `staging-deploy` Makefile targets use "deploy" in the Release sense; they will be renamed `*-release` (old names kept as deprecated aliases).

This is ops/infra vocabulary, deliberately **not** added to `CONTEXT.md` (a product glossary).

## Context

Today a Release is `make {env}-deploy` → `git pull` → `docker compose up -d --build --force-recreate` (Makefile:264). **The image is built on the live EC2 host.**

On 2026-06-30 a prod Release ran the frontend `next build` + Sentry source-map upload on the live `t3.medium` (4 GB, no swap) *while it was serving traffic*. Prod's live working set + the build crossed the memory ceiling → page-cache thrash (no OOM-kill fired; no swap to spill to) → the SSM agent and nginx stalled on major faults → ~37 min outage until an EC2 reboot. No customer transactions were affected (one zero-energy ADMIN session rode through; DB is on RDS, untouched). Root cause: **building on the live host.** Staging was unaffected only because it wasn't building and carries a negligible working set — *not* an infra difference (both are identical `t3.medium`).

## Decision

Building moves **off the live host**. **GitHub Actions** builds the images, pushes them to **Amazon ECR**, and a Release updates an environment by **pulling a pre-built image** — the host never runs `docker build`.

### Artifact identity & rollback (accepted)

- **Every image is tagged with the immutable git SHA** it was built from (`…/ocpp-frontend:sha-<sha>`). One SHA = one atomic set of images (backend/frontend/nginx). The SHA tag is canonical; **never release from `:latest`**.
- A moving per-env pointer tag (`:staging`, `:prod`) marks "what's live" for humans/tooling, but the SHA is the source of truth.
- **Rollback = re-point the env to a prior SHA and `up -d` (pull, no build)** — seconds, because the prior image already exists in the registry.
- ECR **lifecycle policy** retains the last ~20 SHA images so rollback targets aren't pruned while storage stays bounded.

### Migration ordering & the rollback-safety contract (accepted)

Image rollback is trivial; **schema is forward-only** (no `aerich downgrade` on live prod — schema disaster recovery is RDS PITR/snapshot, not a routine rollback). To keep SHA-image rollback safe despite that asymmetry:

- **Expand/contract is a hard rule.** Every migration in a release must be **backward-compatible with the currently-running (old) image** — additive only (new nullable columns, tables, indexes). Anything destructive or tightening (drop, rename, `NOT NULL` without default) is **split across two releases**: R1 expands (add nullable + backfill + dual-write); R2 contracts (tighten/drop) once the new code is fully live. This guarantees the previous image always tolerates the live schema, so image rollback never needs a schema rollback.
- **Migrate-before-swap.** Per release: `compose pull` → run `aerich upgrade` from the **new** image as a one-shot (without touching the serving container) → `compose up -d` to swap serving traffic. Backward-compatibility (above) makes the brief old-code-on-new-schema window harmless.
- **Migrations become a discrete, explicitly-invoked step — not auto-run in the entrypoint.** *Current reality (2026-06-30): this is NOT how it works today* — `backend/docker-entrypoint.sh` runs `aerich upgrade` on every backend boot and then hardcodes `exec uvicorn`, **ignoring any passed command** (so `docker compose run backend aerich upgrade` starts a server, not a migration). Auto-migrate-on-boot is a foot-gun with `force-recreate`/replica startup and defeats migrate-before-swap. The pipeline work therefore must (a) remove `aerich upgrade` from the entrypoint and (b) make the entrypoint honor a passed command (`exec "$@"`) so the one-shot migrate works. Tracked in issue `05`. Once removed, **every release must run the migrate step** or the schema will not advance.
- **Blocking DDL runs out-of-band before the release** (e.g. `CREATE INDEX … CONCURRENTLY`, the existing `{env}-create-log-indexes` pattern, migration 44 precedent). The release checklist gains a flag: *contains migration? expand-only? blocking?*

### Images built vs pulled (accepted)

CI builds the **three source images** — `backend`, `frontend`, `nginx` — each to its own ECR repo, all tagged with the same git SHA (atomic release set). **`postgres`, `redis`, `certbot` are upstream images, pulled by version tag, never built.** Only the **frontend** build consumes args/secrets; the backend and nginx builds take none.

### Release trigger & gating (accepted)

- **CI builds and pushes only — it never touches a running server.** A push to `develop`/`deploy` triggers a build + push of SHA-tagged images to ECR. CI's AWS permission is ECR-push and nothing else.
- **Releases are human-run from the laptop over SSM** — the access path already in use. `make {env}-release` does `pull → one-shot aerich upgrade → up -d` (no build). Both staging and prod are released this way.
- **Prod is always explicit** — never auto-released on a push. A human promotes a specific SHA already validated on staging.

### Auth (accepted)

**GitHub OIDC**, no static AWS keys in GitHub. A one-time IAM OIDC provider for `token.actions.githubusercontent.com` + an IAM role whose trust policy is scoped to `repo:jeethjoseph/ocpp-server:*` (tightened to release branches where practical) and whose permission policy is limited to **ECR push on the `ocpp-*` repos only**. Each CI run mints a short-lived token; nothing long-lived is stored. (OIDC works on a private, personal-account repo on the free plan — no org/public-repo/paid feature required.)

### Secrets model (accepted)

The discriminator is mechanical: **a value goes to GitHub only if the frontend Dockerfile declares an `ARG` for it.** Everything else is runtime and stays on the host.

- **On the host (`.env.prod`/`.env.staging`), never in GitHub** — all runtime secrets: `DB_PASSWORD`, `CLERK_SECRET_KEY` (also the frontend's server-side runtime, not a build arg), `CLERK_WEBHOOK_SECRET`, **all Razorpay** (`RAZORPAY_KEY_ID`/`KEY_SECRET`/`WEBHOOK_SECRET` — backend-only; the frontend gets `key_id` at runtime via the API), `NEW_RELIC_LICENSE_KEY` (the real backend key), `REDIS_URL`, and the ~50 other tuning/identity vars.
- **GitHub Actions Variables (public by design — `NEXT_PUBLIC_*` inline into the browser bundle, or plain identifiers):** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `NEXT_PUBLIC_APP_URL`, the five `NEXT_PUBLIC_NEW_RELIC_*`, `NEXT_PUBLIC_WALLET_CHARGING_ENABLED`, `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENVIRONMENT`, `SENTRY_ORG`, `SENTRY_PROJECT`.
- **GitHub Actions Secret (the only genuine one):** `SENTRY_AUTH_TOKEN`. It is **removed from the host `.env.*`** once CI owns the build, shrinking its exposure surface.
- **AWS access:** the OIDC role ARN (a non-secret identifier), via the role above.

## Considered options

- **Keep building on-host, add swap / bump to t3.large.** Swap is adopted as an *interim* band-aid so the currently-stuck release can land, but it doesn't fix the class: the heavy build still runs on the live host against the live working set. Rejected as the end state.
- **Registry: GHCR instead of ECR.** Rejected — ECR is native to the AWS account the hosts already authenticate to (instance role), avoiding a GitHub pull-token on the host. GHCR would add a host-side credential for no gain.
- **CI provider: AWS CodeBuild instead of GitHub Actions.** Rejected — repo is GitHub-hosted; GHA needs no extra source integration and its runners (16 GB) dwarf the 4 GB host. CodeBuild adds IAM/buildspec overhead for no benefit at this scale.
- **Full CD (CI releases straight to prod).** Rejected — migrations need human judgment (expand-only? blocking DDL run out-of-band first?), and granting CI SSM/deploy rights into prod is a large security surface. Build-only + human promotion keeps prod changes attended.
- **Static AWS keys in GitHub.** Rejected — long-lived, broad-blast-radius credential; OIDC is strictly safer.

## Consequences

- **Compose refactor:** prod/staging `build:` blocks for backend/frontend/nginx become `image: ${ECR}/ocpp-<svc>:${GIT_SHA}`. Local `docker-compose.yml` stays build-based for dev. A prod/staging image-ref override is the cleanest split.
- **The frontend ARG/ENV trap moves, it doesn't vanish** (CLAUDE.md): every build value must still have a matching `ARG` in `frontend/Dockerfile`; CI now supplies them from Actions variables/secrets, with `SENTRY_AUTH_TOKEN` injected inline on the build `RUN` so it never lands in an image layer.
- **Makefile:** `{env}-deploy`/`{env}-rebuild` (which run `up --build`) are replaced by `{env}-release` (`pull → one-shot migrate → up`, no build). Old `*-deploy` names kept as deprecated aliases. The word **Release** is reserved for this; **Deploy** stays the firmware→charger term (not added to `CONTEXT.md`).
- **Rollback** becomes retag-prior-SHA + `up -d` (seconds), guaranteed schema-safe by the expand/contract rule.
- **Release checklist** gains: *contains migration? expand-only? blocking (run CONCURRENTLY out-of-band first)?*
- **ECR lifecycle policy** retains ~20 SHA images per repo.
- **Prerequisite cleanup:** the dormant rollback `postgres` service/volume in staging+prod compose (both RDS validation windows now closed) should be removed first via the tracked decommission issue, so the release pipeline operates on a clean compose.
- **No multi-arch needed** — hosts are t3/x86_64, matching `ubuntu-latest` runners. (Revisit only on a move to Graviton/arm64.)
- **Optional hardening:** pin upstream `postgres`/`redis`/`certbot` by digest for fully reproducible releases.
- **Entrypoint change is a prerequisite for the discrete migrate step:** removing `aerich upgrade` from `backend/docker-entrypoint.sh` and making it `exec "$@"` (issue `05`) is a behavior change — pre-change, every backend boot silently migrated; post-change, the release flow owns migration. The release runbook + `make {env}-release` must guarantee the migrate runs, else schema drift goes unnoticed.
