
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

## Wallet ledger pattern (CRITICAL — non-obvious from the code alone)

The wallet is an **event-sourced ledger** post migrations 32 → 33 → 34. If you're touching `wallet_service.py`, `wallet_session_service.py`, `wallet_transaction`, or any code path that reads or writes a balance, read this:

- **There is no stored `wallet.balance` column.** Balance is derived: `WalletService.get_balance(wallet_id)` runs a `SUM` over `wallet_transaction`. Do not add a stored balance back. Reads are cheap (~1 ms at N=5000) with the Redis cache (`wallet_balance:{wallet_id}`) in front and a plain index on `(wallet_id)`.
- **`wallet_transaction.amount` is always non-negative.** Direction is in `type` (`TOP_UP` credits, `CHARGE_DEDUCT` debits). Enforced by `WalletTransaction.save()` validator + DB `CHECK (amount >= 0)`. Never write a negative amount. `bulk_create` bypasses the Python validator but the DB CHECK still catches it.
- **Only `TOP_UP` rows with `payment_metadata.status = 'COMPLETED'` count toward balance.** PENDING rows exist during the Razorpay confirmation window — they must NOT credit. CHARGE_DEDUCT rows always count.
- **Cache invalidation happens AFTER the outer transaction commits.** `process_transaction_billing` and `process_wallet_topup` are split into thin outer wrappers + `@atomic`-decorated `_do_*` inner functions; the wrapper invalidates the cache after the inner returns. Do not move invalidation back inside the `in_transaction()` block — concurrent readers would repopulate stale data.
- **Wallet-session budget cap mirrors QR.** On StartTransaction, `WalletSessionService.cache_session_on_start` snapshots the balance into `wallet_session:{txn_id}`. On every MeterValues frame, `check_balance_and_auto_stop` schedules `RemoteStopTransaction` via `safe_create_task` when `cost ≥ budget`. **Flag-less, at-least-once dispatch** — energy is monotonic so a lost stop self-heals on the next tick. Do not add an idempotency flag; duplicate RemoteStops are idempotent at the charger.
- **Negative derived balance is observable, not impossible.** If the budget cap fails to fire (charger offline, network blip), `get_balance` returns a negative number, logs a warning, and emits `Custom/Wallet/NegativeBalance`. Do not clamp at the source-of-truth layer. UI/API may clamp for display.
- **Drift detection**: `backend/scripts/reconcile_wallet_balance.py` is the nightly cron. See the rollback runbook in the comprehensive architecture doc for the cron entry.

If you find yourself reaching for `wallet.balance` or writing a negative `amount`, stop and re-read this section.

## Environments
- **Production**: `app.voltlync.com` — branch `deploy`, `docker-compose.prod.yml` + `.env.prod`, `make prod-*` targets
- **Staging**: `staging.voltlync.com` — branch `develop`, `docker-compose.staging.yml` + `.env.staging`, `make staging-*` targets
- Both share the same Clerk app and Razorpay **live** keys (QR payments require live mode)
- Razorpay webhook handlers gracefully skip "not found" transactions (cross-environment events) — do not change this to raise errors

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

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles using default label strings (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.