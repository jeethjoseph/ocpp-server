Status: ready-for-human

# Procure + populate new env vars in `.env.prod` on prod EC2

## What to build

Add ~15 new env vars to `/home/ec2-user/ocpp-server/.env.prod` on the prod EC2 instance. Some values are deterministic (defaults from `.env.prod.example`). Others require procurement: GSTIN from finance/legal, Sentry+NR keys from those respective consoles.

The deploy in issue 04 reads `.env.prod` via the `--env-file` flag during `docker compose up -d`. Missing-or-empty values trigger silent degradation (no invoices, no frontend telemetry) rather than crash, so the deploy will technically succeed even with gaps. **The goal is to avoid landing in degraded state.**

Backup the existing `.env.prod` to `.env.prod.pre-deploy-2026-05-27` before editing — that's the file we restore on rollback.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Update `.env.prod` via PR / git | `.env.prod` is gitignored on purpose — contains live secrets. It lives only on the EC2 host. |
| Use AWS Secrets Manager / Parameter Store | Same Q3 decision we locked in the RDS migration interview — `.env.staging`/`.env.prod` is the canonical pattern. Don't drift. |
| Skip the pre-edit backup | Mistyped `.env.prod` can cause container restart-loops. 5 seconds of `cp` makes rollback a 1-step revert. |

## Procurement checklist

Before touching the file, gather these values:

### Backend (REQUIRED — set or features degrade silently)

| Var | Where to get it | Risk if empty |
|---|---|---|
| `VOLTLYNC_GSTIN` | Finance/legal — the actual 15-char GSTIN registered to VOLTLYNC PRIVATE LIMITED | **GST invoices skip generation entirely** |
| `VOLTLYNC_ADDRESS` | Finance/legal — registered business address | Address blank on invoices (regulatory issue) |
| `VOLTLYNC_BUSINESS_NAME` | Has default `VOLTLYNC PRIVATE LIMITED` — confirm exact name | Default works |
| `VOLTLYNC_STATE` / `VOLTLYNC_STATE_CODE` | Has defaults `Kerala` / `32` — confirm | Default works for Kerala-registered entity |
| `AWS_S3_INVOICE_BUCKET` | From issue 01 — `voltlync-invoices-prod` | Invoice PDFs not persisted (lost on restart) |
| `AWS_S3_FIRMWARE_BUCKET` | From issue 01 — `voltlync-firmware-prod` | Firmware uploads fall back to local disk |
| `AWS_REGION` | `ap-south-1` | S3 calls fail |

### New Relic APM (backend already on staging; production agent needs license + browser app)

| Var | Where to get it |
|---|---|
| `NEW_RELIC_LICENSE_KEY` | NR account → API keys → Ingest License (same one staging uses, can be reused) |
| `NEW_RELIC_APP_NAME` | Set to `OCPP-Server-Production` (must differ from staging — see CLAUDE.md Env vars section) |
| `NEW_RELIC_MONITOR_MODE` | `true` |
| `NEW_RELIC_DISTRIBUTED_TRACING_ENABLED` | `true` |
| `NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED` | `true` |

### New Relic Browser (NEW — needs a Browser app created for prod)

| Var | How to get it |
|---|---|
| `NEXT_PUBLIC_NEW_RELIC_BROWSER_LICENSE_KEY` | NR UI → + Add Data → Browser monitoring → NPM install → name app `VoltLync Frontend - Production` → extract from generated snippet |
| `NEXT_PUBLIC_NEW_RELIC_APPLICATION_ID` | Same snippet |
| `NEXT_PUBLIC_NEW_RELIC_ACCOUNT_ID` | Same snippet |
| `NEXT_PUBLIC_NEW_RELIC_TRUST_KEY` | Same snippet |
| `NEXT_PUBLIC_NEW_RELIC_AGENT_ID` | Same snippet |

### Sentry — backend + frontend

| Var | Where to get it |
|---|---|
| `SENTRY_ENABLED` | `true` |
| `SENTRY_DSN` | Sentry → ocpp-server prod project → Client Keys (DSN) |
| `SENTRY_ENVIRONMENT` | `production` |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` (default — 10%) |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.1` |
| `NEXT_PUBLIC_SENTRY_DSN` | Sentry → ocpp-frontend prod project → Client Keys (DSN). NOTE: separate Sentry project from backend |
| `SENTRY_ORG` | `idofthings` (already documented in `.env.prod.example`) |
| `SENTRY_PROJECT` | `ocpp-frontend` |
| `SENTRY_AUTH_TOKEN` | Sentry → Settings → Custom Integrations → create token with `project:releases` + `project:read` scopes. **Build-time only — needed for source map upload during `next build`.** |

### Razorpay payouts (OFF by default — flip on later)

| Var | Recommended |
|---|---|
| `RAZORPAY_ROUTE_ENABLED` | `false` for this deploy. Enable in a focused follow-up after the deploy stabilizes. |
| `WALLET_SETTLEMENT_ENABLED` | `false` — Razorpay hasn't enabled Direct Transfer on the merchant yet |
| `MINIMUM_TRANSFER_AMOUNT` | `1.00` |
| `MAX_TRANSFER_RETRIES` | `3` |
| `FRANCHISEE_PAYOUT_RETRY_INTERVAL_SECONDS` | `600` |
| `STUCK_PAYOUT_CHECK_INTERVAL_SECONDS` | `3600` |
| `STUCK_PAYOUT_THRESHOLD_HOURS` | `24` |

### OCPP/server tuning (all optional, but worth setting explicitly)

Per `.env.prod.example` defaults — `ZERO_ENERGY_TIMEOUT_SECONDS=7200`, `SOCKET_GRACE_PERIOD_SECONDS=300`, `MAX_DISCONNECT_RESETS_WITHOUT_PROGRESS=3`, `MAX_RESUME_GAP_SECONDS=900`, `DISCONNECT_SUSPEND_TIMEOUT_SECONDS=180`, `RAZORPAY_INSTANT_REFUND_ENABLED=true`, `FIRMWARE_PUBLIC_BASE_URL=https://app.voltlync.com`, plus the 4 firmware timing vars.

## What to do

### 1. Backup existing `.env.prod`

```bash
# From SSM session on prod EC2:
cd /home/ec2-user/ocpp-server
cp .env.prod .env.prod.pre-deploy-2026-05-27
ls -lh .env.prod.pre-deploy-2026-05-27
```

### 2. Append new env vars

Either:
- Use `nano /home/ec2-user/ocpp-server/.env.prod` interactively and paste the block
- OR generate the block locally with all procured values and append via `cat >>` in SSM

Recommended structure: append the new block at the END of `.env.prod`, separated by a comment header. This keeps the existing lines untouched and the diff readable.

### 3. Sanity-grep before deploy

```bash
# Confirm the critical ones are non-empty:
grep -E "^(VOLTLYNC_GSTIN|AWS_S3_INVOICE_BUCKET|AWS_S3_FIRMWARE_BUCKET|NEW_RELIC_LICENSE_KEY|SENTRY_DSN)=" .env.prod
# Each line should show value=<non-empty>
# If any is empty or missing, fix before proceeding to issue 04
```

### 4. Verify docker-compose parses correctly with new env

```bash
$(PROD_COMPOSE) config --quiet && echo OK
```

Should print `OK`. If it complains about an undefined variable, find which one and add it.

## Definition of done

- `.env.prod.pre-deploy-2026-05-27` exists as a backup
- All REQUIRED vars (above) have non-empty values in `.env.prod`
- `docker compose -f docker-compose.prod.yml --env-file .env.prod config --quiet` returns 0
- Procurement of any deferred values (e.g. Sentry frontend if you're skipping it for now) is documented somewhere outside this issue so it doesn't get forgotten
