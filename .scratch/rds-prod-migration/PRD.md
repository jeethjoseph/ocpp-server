# Production DB migration: Docker postgres → AWS RDS Postgres

## Summary

Move the production environment's primary database off the in-container `ocpp-postgres-prod` Docker service onto an AWS RDS for Postgres instance in the same VPC. **Multi-AZ from day one** (unlike staging). Mirrors the staging cutover playbook (see `.scratch/rds-staging-migration/`) with prod-specific hardening.

## Why production now

Pre-conditions, all of which should be true before triggering this work:

- [ ] Staging RDS has been stable for at least the full **14-day validation window** (started 2026-05-27)
- [ ] Issue 07 of the staging migration has decommissioned the Docker postgres on staging
- [ ] No RDS-related Sentry exceptions in the staging window
- [ ] At least one Aerich migration ran cleanly against staging RDS
- [ ] At least one OCPP simulator E2E test passed against staging RDS
- [ ] NR APM p95 latency on staging within ~10% of pre-cutover baseline
- [ ] Backup + restore drill performed at least once on staging (PITR or snapshot)

Don't start the prod migration until **all** are checked.

## Differences from staging

| Dimension | Staging | Production |
|---|---|---|
| Multi-AZ | Single-AZ (cheap) | **Multi-AZ** — synchronous standby + auto-failover, real customer data at stake |
| Instance class | `db.t4g.micro` | `db.t4g.small` minimum; `db.t4g.medium` if NR APM shows headroom is tight |
| Storage | 20GB gp3 | **50GB** gp3 with auto-scaling to 200GB (prod data grows faster) |
| Backup retention | 14 days | **30 days** (matches your other compliance posture) |
| Performance Insights retention | 7 days | **31 days** (paid tier — worth it for prod) |
| Validation window post-cutover | 14 days | **28 days** before decommission |
| Downtime tolerance | Casual — ~10 min OK | **Strict** — must be ≤15 min, ideally in 02:00-04:00 IST window |
| Cutover dump format | Plain SQL | Plain SQL (still small enough); but consider `pg_dump -F c -j 4` if prod is now >2GB |
| Razorpay webhook handling during downtime | Not relevant on staging | **Critical** — webhooks queue/retry; must verify no events are dropped (see below) |

## Scope

**In scope:**
- Production environment only
- RDS Postgres 15.x (match current prod Docker postgres major version) in `ap-south-1`
- Multi-AZ, `db.t4g.small`+, 50GB gp3, 30-day backups
- TLS `verify-full` (CA bundle already baked in image from staging cutover)
- Password auth, master + app user separation, secrets in `.env.prod`
- Cutover runbook + extensive rollback path
- 28-day validation window before decommissioning Docker postgres

**Out of scope:**
- Aurora (defer until scale forces it)
- Read replicas (premature; backend isn't read-bound)
- RDS Proxy (only if connection counts climb)
- IAM database auth (defer)
- Cross-region replication (overkill for current scale)

## Architecture summary (target state)

```
EC2 ap-south-1a (i-0df24c96c4d5e890a, ocpp-server-prod)
  ├─ ocpp-backend-prod   ──────────► AWS RDS ocpp-prod-db (Multi-AZ)
  ├─ ocpp-frontend-prod                  primary  : ap-south-1a (or 1b)
  ├─ ocpp-redis-prod                     standby  : different AZ
  ├─ ocpp-nginx-prod                     30-day backups, PITR
  └─ ocpp-postgres-prod (rollback target during 28-day window)
```

## Locked decisions (carried from staging + prod-specific)

| # | Decision | Notes |
|---|---|---|
| 1 | RDS Postgres 15.x, Multi-AZ, `db.t4g.small`, 50GB gp3, 30-day backups | Multi-AZ is the prod-specific upgrade; everything else is "staging spec + headroom" |
| 2 | Default VPC `vpc-0...` (whatever prod EC2's VPC is), subnet group across 3 AZs, dedicated RDS SG inbound from prod EC2 SG only, not publicly accessible | Same pattern as staging |
| 3 | Password auth, both passwords in `.env.prod` | Same convention as staging — DO NOT switch to Secrets Manager mid-migration |
| 4 | TLS `verify-full` with the AWS RDS CA bundle (already baked into image) | No code change needed; just set `DB_SSL_MODE=verify-full` at cutover |
| 5 | `ocpp-prod-db` / `ocpp_admin` / `ocpp_prod` / `ocpp_prod_db` | Keeps DB+user identical to current Docker postgres |
| 6 | `pg_dump | pg_restore` cutover, < 15 min downtime | Use `pg_dump -F c -j 4` if prod DB exceeds 2GB; plain SQL otherwise |
| 7 | Three-tier validation + OCPP simulator E2E + **Razorpay webhook drain** | Webhook check is prod-only |
| 8 | `prod-backup-db` / `prod-restore-db` warn-and-exit post-cutover | Already a pattern from staging |
| 9 | Update memories/docs in-place; add prod-specific subsections | Same as staging |
| 10 | **28-day validation window**; decommission via separate PR | Longer than staging's 14 days because the rollback cost is higher |

## Cost impact (Mumbai monthly, USD)

| Component | Pre-migration | Post-migration | Delta |
|---|---|---|---|
| EC2 t3.medium | $30.50 | $30.50 | $0 |
| EBS root 30GB gp3 | $2.50 | $2.50 | $0 |
| RDS db.t4g.small Multi-AZ | — | $70 | +$70 |
| RDS gp3 50GB | — | $4.15 | +$4.15 |
| RDS backup storage (30-day, ~1.5x DB size avg) | — | ~$5 | +$5 |
| Performance Insights (31-day retention) | — | $7 | +$7 |
| **Total** | **$33** | **~$119** | **+$86** |

After post-migration EC2 downsize to `t4g.small` (a follow-up project, same as staging): net cost becomes ~$95 — about $60/mo more than today for **synchronous Multi-AZ HA + automated backups + PITR + managed patching**.

## Pre-cutover hardening (the staging lessons applied)

Every one of these is gated by a checkbox before Phase 1 of the cutover can fire:

- [ ] **Grep ALL DB-connect call sites** — confirm each uses `db_ssl.get_ssl_config()`:
  ```bash
  grep -rn "asyncpg.connect\|psycopg.connect\|pg_isready\|psql -h" \
    --include="*.sh" --include="*.py" backend/
  ```
  Known sites that must all pass: `backend/database.py`, `backend/tortoise_config.py`, `backend/docker-entrypoint.sh`. Any new hit must use the helper or be explicitly justified.

- [ ] **Provision RDS at least 24 hours before the cutover window.** Performance Insights + CloudWatch Logs exports add provisioning time (~20 min observed on staging). Don't bundle into the maintenance window.

- [ ] **Dry-run the entrypoint pre-flight against RDS** before the cutover:
  ```bash
  sudo docker run --rm \
    -e DB_HOST=<RDS endpoint> -e DB_USER=ocpp_prod -e DB_PASSWORD=<app pw> \
    -e DB_NAME=ocpp_prod_db -e DB_SSL_MODE=verify-full -e DB_PORT=5432 \
    ocpp-server-backend:latest /app/docker-entrypoint.sh
  ```
  If the entrypoint reaches "Database is ready!" and "Starting OCPP Backend...", the SSL config is good. If it loops on "Waiting for database...", abort and debug.

- [ ] **Razorpay webhook posture check:**
  - Confirm `razorpay_webhook_handler` retries / dead-letters cleanly when DB is unreachable
  - Note Razorpay's webhook retry policy (24 hours, exponential backoff) — short downtime should be fully recoverable
  - Check `webhook_event` table size 1 hour pre-cutover; track it 1 hour post-cutover to detect dropped events
  - If any payment-relevant webhooks fire during the downtime window, manually replay from the Razorpay dashboard post-cutover

- [ ] **OCPP simulator E2E run against staging RDS** within the 24 hours before prod cutover, as the final smoke test of the entire RDS-backed code path.

- [ ] **Maintenance announcement** sent to all stakeholders ≥4 hours before the cutover window.

## Cutover sequence (mirrors staging issue 05 with prod hardening)

Same 5 phases as staging. Time budget: 10-15 min planned downtime.

| Phase | What | Time | Difference from staging |
|---|---|---|---|
| **0** (T-24h) | Final pre-cutover grep + entrypoint dry-run + simulator E2E | 30 min | New for prod |
| **1** (T+0:00) | Stop backend, backup `.env.prod`, final `pg_dump` | 2-3 min | Larger DB → longer dump |
| **2** (T+0:03) | Restore dump to RDS as app user | 3-5 min | Same |
| **3** (T+0:08) | Row count parity across all critical tables (especially `wallet_transaction`, `qr_payment`, `commission_ledger_entry`, `gst_invoice`) | 30s | Same logic; extra tables for prod |
| **4** (T+0:09) | Update `.env.prod` (`DB_HOST`, `DB_PASSWORD`, `DB_SSL_MODE`), restart backend | 1 min | Same |
| **5** (T+0:10 – T+0:20) | Tier 1 + Tier 2 + Razorpay webhook drain verification + OCPP simulator E2E | 10 min | Razorpay + simulator are new for prod |

## Razorpay webhook drain (Phase 5 prod-specific)

Pseudo-procedure post-cutover:

1. Query `webhook_event` count + most recent `received_at` on RDS — compare to pre-cutover snapshot
2. If gap exists, query Razorpay dashboard for events delivered during the downtime window
3. For any payment-status-changing events in that window, manually replay or reconcile by querying Razorpay API directly + writing to `qr_payment` / `commission_ledger_entry` if needed
4. Confirm `stuck_payout_detector` and `billing_retry_service` schedulers picked up where they left off (NR APM should show their custom transaction traces firing on the usual cadence within ~1 hour)

## Rollback path

Same shape as staging:
1. `cp .env.prod.pre-rds-cutover .env.prod`
2. `$(PROD_COMPOSE) restart backend`
3. Backend talks to Docker postgres again, data intact

Rollback time: ~60 sec. Data integrity preserved because backend was stopped before final dump (zero writes after dump completed).

If rollback is invoked AFTER Phase 4, any writes that landed on RDS between Phase 4 completion and rollback decision are lost. With 10-15 min total downtime + Razorpay webhook retries, this is bounded to a small window. **Mitigation: if rollback is needed >5 min after Phase 4, also replay Razorpay webhooks for the rollback window.**

## Decommission triggers (28-day validation window)

All required:

- [ ] Zero RDS-related Sentry exceptions for 14 consecutive days
- [ ] No CloudWatch RDS alarms triggered
- [ ] At least one Aerich migration ran cleanly against prod RDS
- [ ] At least one full Razorpay webhook + GST invoice cycle completed cleanly against RDS
- [ ] At least one OCPP simulator E2E test passed against prod RDS
- [ ] NR APM p95 latency within ~10% of pre-cutover baseline
- [ ] Backend restarted at least once during the window without breaking
- [ ] One successful PITR drill (restore to a scratch RDS instance from a backup)

## Issues

Issue files will be created when this project becomes active. They will closely mirror `.scratch/rds-staging-migration/issues/01-07.md`, swapping staging → prod everywhere, adding the prod hardening checklist as a new pre-Phase-0 issue, and increasing the validation window in issue 07.

When activating:

- `00-prod-cutover-pre-hardening.md` — the grep + entrypoint dry-run + simulator E2E + Razorpay webhook check (new for prod)
- `01-provision-rds-prod.md` — Multi-AZ provisioning, larger instance, longer backup retention
- `02-no-op.md` — backend code unchanged from staging cutover; CA bundle + db_ssl helper already in image
- `03-compose-and-env-changes-prod.md` — mirror staging issue 03 for `docker-compose.prod.yml` + `.env.prod.example` + Makefile prod targets
- `04-app-user-and-trial-restore-prod.md` — mirror staging issue 04 for prod
- `05-cutover-runbook-prod.md` — mirror staging issue 05 + Razorpay webhook drain phase
- `06-doc-and-memory-updates-prod.md` — collapse the staging-vs-prod asymmetry sections in CLAUDE.md and v1 docs
- `07-decommission-docker-postgres-prod.md` — 28-day window, otherwise mirror of staging issue 07
