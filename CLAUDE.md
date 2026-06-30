
## How I Work
- Always create a plan before coding
- Ask me before making architectural changes
- When migrations are necessary I prefer to do it with Aerich. Only create migrations necessary after you verify that it is impossible to generate it with Aerich.
- Keep functions under 40 lines
- Commit-ready code only — no TODOs in final output
- At the start of every session refer to /Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/llm-context-document.md
- For larger context and architecture related context refer to this /Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/comprehensive-architecture-documentation.md
- When you are done with making changes, update these documents - Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/llm-context-document.md, /Users/raalshasan/makaratech/idofthings/ocpp-server/docs/v1/comprehensive-architecture-documentation.md

## Build verification (before declaring done)
- **Frontend**: after any `frontend/` edit, run `cd frontend && npm run build` locally. `next lint` and `tsc --noEmit` are NOT sufficient — the production build enforces `@typescript-eslint/no-unused-vars`, `react/no-unescaped-entities`, and other rules the scoped lint misses.
- **Backend**: run `docker exec ocpp-backend pytest` for the affected test files. Known pre-existing flake: 6 tests in `tests/test_integration.py` + `tests/test_post_boot_state.py` ERROR with `column "gst_rate_percent" does not exist` — a sync TestClient × Tortoise cross-loop schema-generation issue, **not** a regression. Verifiable by `git stash` then re-running the same tests. Treat these as the baseline for the full-suite run.
- **Docker build parity**: when changes touch the build (new imports, new deps, config), run `docker compose build frontend` / `docker compose build backend` locally to catch image-level failures before they hit staging.
- Never declare a change "done" based only on `tsc` output or partial lint runs — staging/prod rebuilds enforce the full ruleset.

## Logs

Both compose files cap container log file growth so nothing fills the host's disk, but they do it differently:

- **`docker-compose.staging.yml`** uses a single `x-default-logging` YAML anchor at the top and every service references it via `logging: *default-logging` — **5 × 50 MB = 250 MB** per container. Added 2026-05-27. New services should reference the same anchor.
- **`docker-compose.prod.yml`** has per-service `logging:` blocks with deliberately different caps — backend gets the most room (20m × 5 = 100 MB), nginx/postgres/redis/frontend smaller (10m × 3 = 30 MB), certbot smallest (5m × 2 = 10 MB). These are tuned for actual write volume per service; don't unify them without reason.

In either env, `docker logs` reads transparently across the rotated files. Don't ship a new service to either compose file without a `logging:` block.

`make staging-logs` / `make prod-logs` (and the per-service variants) default to `--tail=100 -f` — last 100 lines for context, then live tail. For full history without follow, run `$(STAGING_COMPOSE) logs > staging.log` and grep the file.

## Wallet ledger pattern (CRITICAL — non-obvious from the code alone)

The wallet is an **event-sourced ledger** post migrations 32 → 33 → 34. If you're touching `wallet_service.py`, `wallet_session_service.py`, `wallet_transaction`, or any code path that reads or writes a balance, read this:

- **There is no stored `wallet.balance` column.** Balance is derived: `WalletService.get_balance(wallet_id)` runs a `SUM` over `wallet_transaction`. Do not add a stored balance back. Reads are cheap (~1 ms at N=5000) with the Redis cache (`wallet_balance:{wallet_id}`) in front and a plain index on `(wallet_id)`.
- **`wallet_transaction.amount` is always non-negative.** Direction is in `type` (`TOP_UP` credits, `CHARGE_DEDUCT` debits). Enforced by `WalletTransaction.save()` validator + DB `CHECK (amount >= 0)`. Never write a negative amount. `bulk_create` bypasses the Python validator but the DB CHECK still catches it.
- **Only `TOP_UP` rows with `payment_metadata.status = 'COMPLETED'` count toward balance.** PENDING rows exist during the Razorpay confirmation window — they must NOT credit. CHARGE_DEDUCT rows always count.
- **Cache invalidation happens AFTER the outer transaction commits.** `process_transaction_billing` and `process_wallet_topup` are split into thin outer wrappers + `@atomic`-decorated `_do_*` inner functions; the wrapper invalidates the cache after the inner returns. Do not move invalidation back inside the `in_transaction()` block — concurrent readers would repopulate stale data.
- **Wallet-session budget cap mirrors QR.** On StartTransaction, `WalletSessionService.cache_session_on_start` snapshots the balance into `wallet_session:{txn_id}`. On every MeterValues frame, `check_balance_and_auto_stop` schedules `RemoteStopTransaction` via `safe_create_task` when `cost ≥ budget`. **Flag-less, at-least-once dispatch** — energy is monotonic so a lost stop self-heals on the next tick. Do not add an idempotency flag; duplicate RemoteStops are idempotent at the charger.
- **Negative derived balance is observable, not impossible.** If the budget cap fails to fire (charger offline, network blip), `get_balance` returns a negative number, logs a warning, and emits `Custom/Wallet/NegativeBalance`. Do not clamp at the source-of-truth layer. UI/API may clamp for display.
- **Drift detection**: `backend/scripts/reconcile_wallet_balance.py` is **obsolete post-migration 33** (queries the dropped `wallet.balance` column). No cron is currently wired. Runtime drift signal is the `Custom/Wallet/NegativeBalance` event emitted by `WalletService.get_balance` — wire a Sentry alert rule on that for ongoing monitoring.

If you find yourself reaching for `wallet.balance` or writing a negative `amount`, stop and re-read this section.

## Environments
- **Production**: `app.voltlync.com` — branch `deploy`, `docker-compose.prod.yml` + `.env.prod`, `make prod-*` targets
- **Staging**: `staging.voltlync.com` — branch `develop`, `docker-compose.staging.yml` + `.env.staging`, `make staging-*` targets
- Both share the same Clerk app and Razorpay **live** keys (QR payments require live mode)
- Razorpay webhook handlers gracefully skip "not found" transactions (cross-environment events) — do not change this to raise errors

## Database tier (both staging and prod on RDS as of 2026-05-28)

Two RDS migrations completed back-to-back: staging on 2026-05-27, prod on 2026-05-28. Local dev still uses Docker postgres.

- **Local dev**: Docker postgres (`docker-compose.yml`). No SSL. Schema-reset via `docker volume rm` is cheap. No change.
- **Staging**: **AWS RDS Postgres `ocpp-staging-db.c1608qm4i94k.ap-south-1.rds.amazonaws.com`**. Single-AZ `db.t4g.micro`, 20GB gp3, 14-day automated backup retention with PITR. TLS `verify-full` required. The local Docker postgres container is still defined in `docker-compose.staging.yml` as a rollback target until the 14-day validation window closes (see `.scratch/rds-staging-migration/issues/07-decommission-docker-postgres.md`).
- **Prod**: **AWS RDS Postgres `ocpp-prod-db.c1608qm4i94k.ap-south-1.rds.amazonaws.com`**. Single-AZ `db.t4g.small`, 50GB gp3 (auto-scaling to 200GB), **30-day** automated backup retention with PITR, Performance Insights enabled (31-day retention), deletion-protection on. TLS `verify-full`. Cutover 2026-05-28 09:30Z, 4 min downtime. Single-AZ initially for cost; bump to Multi-AZ via `aws rds modify-db-instance --multi-az` when revenue justifies (+$35/mo, zero downtime). Docker postgres in `docker-compose.prod.yml` remains as rollback target through the **28-day** validation window (longer than staging's 14d because prod rollback cost is higher). Decommission per `.scratch/rds-prod-migration/` issue 07-equivalent after triggers all-green.

Both RDS instances use the same AWS RDS global CA bundle baked into the backend image at `/etc/ssl/rds-ca-bundle.pem` during `docker build`. No code change needed when adding new RDS instances — just point `DB_HOST` + set `DB_SSL_MODE=verify-full` in the env file.

### SSL config contract

The single source of truth is `backend/db_ssl.py`'s `get_ssl_config()` helper. Three places must use it; if you change DB connection logic, search for ALL of them:

1. `backend/database.py` — runtime DSN for the live app
2. `backend/tortoise_config.py` — Aerich CLI config
3. `backend/docker-entrypoint.sh` — pre-flight wait-for-DB loop (the trap that bit the staging cutover — see [[feedback-check-entrypoint-during-db-config-changes]])

Env-var contract for SSL:
- `DB_SSL_MODE=` (unset/empty) → legacy behavior: `disable` for `postgres`/`localhost`/`127.0.0.1` host, `require` otherwise. This is what local dev uses.
- `DB_SSL_MODE=verify-full` → TLS with CA validation. Required for RDS. Uses the CA bundle baked into the image. Set on both `.env.staging` and `.env.prod`.
- `DB_SSL_MODE=require` → TLS without cert validation. Avoid for new uses; verify-full is strictly better.

### Tooling

| Action | Staging (RDS) | Prod (RDS) |
|---|---|---|
| Ad-hoc psql shell | `make staging-rds-shell` | (parallel target not yet wired — use the same pattern: `docker exec -e PGPASSWORD=$DB_PASSWORD ocpp-postgres-prod psql -h ocpp-prod-db.c1608qm4i94k.ap-south-1.rds.amazonaws.com -U ocpp_prod -d ocpp_prod_db`) |
| Backups | RDS automated daily snapshots + PITR (managed) | Same — RDS automated daily snapshots + PITR (managed) |
| Restore | RDS Console → PITR or snapshot restore | Same |
| `make {env}-backup-db` / `{env}-restore-db` | warn-and-exit (post-cutover) | warn-and-exit (post-cutover) |

### Cutover artifacts preserved

Per-environment safety nets, kept until each validation window closes:

- **Staging** (14-day window): `/home/ec2-user/ocpp-server/backups/staging_cutover_20260527T054652Z.sql` (~469MB) + `.env.staging.pre-rds-cutover`
- **Prod** (28-day window): `/home/ec2-user/ocpp-server/backups/prod_cutover_20260528T093009Z.dump` (117MB, custom format) + `.env.prod.pre-rds-cutover` + the Docker postgres container itself (still running but receiving zero writes since 2026-05-28 09:30Z)

Rollback in either window: `cp .env.{env}.pre-rds-cutover .env.{env} && docker compose ... up -d backend`. Sub-minute.

## Env vars (CRITICAL — read before adding any new env var)

**Adding a new env var to `.env.example` / `.env.staging.example` / `.env.prod.example` is NOT enough.** Docker compose's `--env-file` flag only loads vars into the *shell where compose runs* (for `${VAR}` substitution in YAML). It does **not** automatically pass them into the container.

For a new env var to reach the Python app inside the container, you must add it to the `environment:` block of the **backend** service in all three compose files:
- `docker-compose.yml` (dev)
- `docker-compose.staging.yml`
- `docker-compose.prod.yml`

Pattern: `- NEW_VAR=${NEW_VAR:-sensible_default}` so missing values fall through to a default rather than empty-string.

Symptom of forgetting: file on disk has the value, `os.getenv("NEW_VAR")` inside the container returns empty / None, `docker exec <container> env | grep NEW_VAR` shows nothing. This wasted half an hour during the GST deploy.

Checklist when adding a new env var:
1. `.env.example` — add with comment + default
2. `.env.staging.example` and `.env.prod.example` — add with the appropriate value for that env
3. `docker-compose.yml` — add to `backend.environment:`
4. `docker-compose.staging.yml` — add to `backend.environment:`
5. `docker-compose.prod.yml` — add to `backend.environment:`
6. `backend/main.py` startup event — log a warning/error if the var is critical and empty (so a misconfigured deploy fails loud)
7. Run `docker compose build backend && docker exec <container> env | grep NEW_VAR` to verify locally before claiming done

## Frontend env vars / build args (CRITICAL — analogous trap to the backend one above)

Frontend env vars are **build-time only** for the production image — the Next.js bundler inlines `NEXT_PUBLIC_*` values when `next build` runs inside the Docker builder stage. Anything not present in `process.env` at that moment ends up as `undefined` in the client bundle.

Frontend has a 5th step the backend doesn't have: **the `frontend/Dockerfile` must declare an `ARG` for every value passed in via `build.args:` in compose, and an `ENV` if Next.js needs to read it at build time.** If you skip this, compose silently sends the build arg, the Dockerfile silently ignores it, and `next build` silently bakes the wrong/empty value into the bundle. No error anywhere. We hit this with Sentry source-map uploads (2026-05-26) — three docker-compose `build.args:` were set, but the Dockerfile had no matching `ARG` declarations, so `@sentry/nextjs` saw `SENTRY_AUTH_TOKEN` as empty at build time and skipped the upload silently.

Symptom: build log claims success, the deployed app behaves as if the var was never set, `docker exec ocpp-frontend-staging env | grep VAR` returns nothing (because runtime envs don't reflect build args anyway).

Checklist when adding a new frontend env var:
1. `frontend/.env.example` — add with comment + safe placeholder
2. `.env.staging.example` and `.env.prod.example` — add to the Frontend section
3. `docker-compose.yml` — only matters for dev (Next.js dev server reads `frontend/.env`); skip unless adding a runtime env override
4. `docker-compose.staging.yml` — add to `frontend.build.args:`
5. `docker-compose.prod.yml` — add to `frontend.build.args:`
6. **`frontend/Dockerfile` — add `ARG VAR_NAME` and (for `NEXT_PUBLIC_*` only) `ENV VAR_NAME=$VAR_NAME` in the builder stage**. Secrets that are only consumed by a single build step (e.g. `SENTRY_AUTH_TOKEN`) should be `ARG`-only and injected inline on that `RUN` line to keep them out of any image layer.
7. Verify: rebuild frontend, then `docker exec ocpp-frontend-<env> sh -c "grep -l <something-that-should-be-baked> /app/.next/static/chunks/*.js | head -3"` — should find references. Or for Sentry: confirm the build log prints `Uploaded XX sourcemaps` and a Release with artifacts shows up in Sentry UI.

## Charger state model (two fields, intentionally)

The `charger` table carries TWO orthogonal state-shaped fields. They are NOT redundant — see **ADR 0008** for the full rationale.

- **`latest_status`** (`ChargerStatusEnum`): what the charger reports via OCPP `StatusNotification`. Values: `Available`, `Preparing`, `Charging`, `SuspendedEVSE`, `SuspendedEV`, `Finishing`, `Reserved`, `Unavailable`, `Faulted`. Written exclusively by the `StatusNotification` handler in `main.py`. Read by the status pill, OCPP routing, billing logic.

- **`availability`** (`ChargerAvailabilityEnum`, added 2026-05-27): what an admin or franchisee has commanded via the `ChangeAvailability` endpoint. Values: `Operative`, `Inoperative`. Written by `routers/chargers.change_charger_availability` and `routers/franchisee_portal.change_availability` on OCPP `Accepted`/`Scheduled` responses (not on `Rejected`). Read by the admin UI toggle.

**Why two fields**: a `Faulted` charger can still be admin-set `Operative` (the admin wants it available; the hardware is broken — orthogonal concerns). A `Charging` charger that admin clicks `Inoperative` goes to `availability=Inoperative` immediately, but `latest_status` stays `Charging` until the session ends per OCPP `Scheduled` semantics. Conflating the two breaks the toggle UX for any charger whose firmware doesn't reliably send a follow-up `StatusNotification` after `ChangeAvailability:Accepted` — see ADR 0008 for the specific bug that surfaced this.

If you ever consider unifying these or deriving one from the other, re-read ADR 0008 first.

## Timestamps (CRITICAL — store UTC, present IST)

**The rule, no exceptions:** the database and the API store and return timestamps in **UTC**. Every surface a *human* reads — admin/franchisee UI, CSV/Excel exports, PDF invoices, anything emailed or downloaded — must convert to **IST (Asia/Kolkata, UTC+5:30)** at the moment of rendering. India is the only operating jurisdiction; a UTC timestamp shown to a human is a **bug**, even when it "looks fine" on an IST-set browser (it breaks for anyone whose browser/OS is on another zone, and for any server-rendered surface). This bit us on the Logs Console — both the table and the CSV shipped UTC (fixed 2026-06-29).

**Never** rely on the ambient/browser timezone to do the conversion for you. `new Date(x).toLocaleString()` *without* an explicit `timeZone` renders in the browser's zone — that is NOT "IST", it's "whatever the admin's laptop is set to". Always pass the zone explicitly.

Canonical converters — use these, don't hand-roll offsets (`+5:30` math silently breaks at no DST but is still the wrong habit):

- **Backend (Python)**: `from utils import to_ist` → `to_ist(dt)` returns a tz-aware IST datetime (naive inputs are assumed UTC, matching Tortoise). For exports keep ISO so it stays machine-parseable: `to_ist(dt).isoformat()` (yields the unambiguous `…+05:30`). Precedents: `routers/invoices.py`, `routers/logs.py` CSV export.
- **Frontend (TS/React)**: `new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })`, or the `formatDateTime` pattern in `app/admin/gst-filings/page.tsx` (per ADR 0012). For IST *calendar* math (date-range presets) use `lib/date-presets.ts` (`istToday()`), never `new Date()` day arithmetic.

**Label the zone** so it's never ambiguous: CSV/export columns are named `*_ist` (e.g. `timestamp_ist`); UI columns showing a bare time should say IST where there's any doubt. When debugging against logs/Sentry/`pg_stat`, remember UI-shared timestamps are IST — subtract 5:30 to match server UTC.

**Checklist when you add or touch a timestamp on any human-facing surface:**
1. Source value is UTC (DB/API) — confirm, don't assume the field is already local.
2. Convert with the canonical helper (`to_ist` / `toLocaleString(..., {timeZone:"Asia/Kolkata"})`) at render/export time — never store IST back.
3. Name/label the output so the zone is explicit (`*_ist`, or an "IST" hint in the header).
4. Add/adjust a test asserting the IST offset or value (e.g. CSV cell ends with `+05:30`) — a bare UTC test passes silently and hides the regression.

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles using default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.