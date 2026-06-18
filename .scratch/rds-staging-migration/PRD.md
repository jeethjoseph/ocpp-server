# Staging DB migration: Docker postgres → AWS RDS Postgres

## Summary

Move the staging environment's primary database off the in-container `ocpp-postgres-staging` Docker service and onto an AWS RDS for Postgres instance in the same VPC. Local dev and prod stay on Docker postgres for now. Prod migration is a separate future project.

## Why now

The current setup — single Docker postgres on a single EC2 in a single AZ, with manual `pg_dump` backups written to the same EC2's disk — has three concrete failure modes that managed RDS fixes:

1. **No point-in-time recovery.** A bad migration or accidental `DELETE` is unrecoverable beyond the last manual backup (24h+ data loss window).
2. **Backups co-located with the DB.** A single EBS failure or EC2 loss destroys both the live DB and every backup.
3. **Coupled lifecycle.** Every deploy bounces postgres alongside backend. EC2 maintenance = DB downtime. No way to restart the app without disturbing the DB.

Industry standard for OCPP CSMS workloads with real money flows is managed Postgres. Verified against the codebase (`models.py`, `services/wallet_service.py`, `services/franchisee_settlement_service.py`, `data_retention_service`): no Postgres extensions are used beyond the default `plpgsql`, no custom tablespaces, no unlogged tables. The DB is 486MB and trivial to migrate.

## Scope

**In scope (this project):**
- Staging environment only
- RDS Postgres 15.x in `ap-south-1`, Single-AZ, `db.t4g.micro`, 20GB gp3, 14-day backups
- TLS `verify-full` with the AWS RDS CA bundle baked into the backend image
- Password auth, master + app user separation, secrets in `.env.staging`
- Code, compose, Makefile, doc, and memory changes
- Cutover runbook with rollback path
- 14-day validation window before decommissioning Docker postgres

**Explicitly out of scope:**
- Production migration (separate future project)
- Local dev changes (stays on Docker postgres)
- EC2 instance downsize (separate follow-up after RDS is stable)
- Multi-AZ (Single-AZ chosen for staging cost; revisit for prod)
- Aurora, RDS Proxy, read replicas (none needed at current scale)
- AWS Secrets Manager for password (defer; `.env.staging` is the current convention)
- IAM database authentication (defer; password auth is fine for staging)

## Architecture summary

```
Before:
  EC2 ap-south-1a (i-00fd9fb3c2b48932a)
  ├─ ocpp-backend-staging   ──┐
  ├─ ocpp-frontend-staging    │
  ├─ ocpp-redis-staging       │ all on the same VPC bridge
  ├─ ocpp-nginx-staging       │
  └─ ocpp-postgres-staging  ◄─┘   ← data lives here

After (within the 14-day validation window):
  EC2 ap-south-1a (i-00fd9fb3c2b48932a)
  ├─ ocpp-backend-staging   ──────► AWS RDS ocpp-staging-db
  ├─ ocpp-frontend-staging                  (ap-south-1, Single-AZ,
  ├─ ocpp-redis-staging                      db.t4g.micro, 20GB gp3,
  ├─ ocpp-nginx-staging                      verify-full TLS)
  └─ ocpp-postgres-staging  (still running but unused; rollback target)

After decommission (~14 days later):
  EC2 ap-south-1a
  ├─ ocpp-backend-staging   ──────► AWS RDS ocpp-staging-db
  ├─ ocpp-frontend-staging
  ├─ ocpp-redis-staging
  └─ ocpp-nginx-staging
```

## Decisions locked during planning

| # | Decision | Rationale |
|---|---|---|
| 1 | `db.t4g.micro` Single-AZ, 20GB gp3, 14-day backups | Cheapest tier adequate for staging traffic; current postgres uses 218MB RAM and 0.3% CPU |
| 2 | Default VPC, subnet group across all 3 AZs, dedicated RDS SG with inbound 5432 only from EC2 SG, not publicly accessible | Standard AWS pattern; security enforced at SG layer; future Multi-AZ promotion has placement flexibility |
| 3 | Password auth, password in `.env.staging` | Matches existing `POSTGRES_PASSWORD` pattern; zero code-flow change; defer IAM auth and Secrets Manager to later projects |
| 4 | TLS `verify-full` with AWS RDS CA bundle baked into backend image | Strongest posture; trivial setup; matches eventual prod posture from day 1 |
| 5 | `ocpp-staging-db` / `ocpp_admin` / `ocpp_staging` / `ocpp_staging_db` | Minimizes migration friction by keeping DB name + app user identical to current Docker setup |
| 6 | `pg_dump` to local file on EC2 in `backups/`, then `psql` restore into RDS; 3-5 min downtime; Docker postgres stays alive as rollback target | Simple, well-understood; rollback is a 30-second `.env.staging` revert |
| 7 | Three-tier validation (mechanical, functional, behavioral) + OCPP simulator E2E run post-cutover | Catches mechanical, schema, data, and behavioral regressions; simulator confirms the OCPP path is fully alive on RDS |
| 8 | `staging-backup-db` / `staging-restore-db` become warn-and-exit with helpful message | Self-documenting; preserves muscle memory while pointing to the new model |
| 9 | Update existing memory + doc files in-place (no new files); env-specific subsections where patterns differ | Single source of truth per topic |
| 10 | 14-day validation window; decommission via separate PR; EC2 downsize as a follow-up project | All-green decommission triggers required; never bundle a destructive change with the cutover |

## Cost impact

| Component | Current monthly (USD) | Post-migration monthly (USD) | Delta |
|---|---|---|---|
| EC2 t3.medium (staging) | $30.50 | $30.50 (unchanged for now) | $0 |
| EBS root volume 30GB gp3 | $2.50 | $2.50 | $0 |
| RDS db.t4g.micro Single-AZ | — | $13 | +$13 |
| RDS gp3 20GB | — | $1.65 | +$1.65 |
| RDS automated backups (14 days) | — | $0 (free up to instance storage) | $0 |
| **Total** | **$33** | **$47.65** | **+$14.65** |

After future EC2 downsize to `t4g.small` (separate project): net cost becomes roughly **flat** vs current state.

## Decommission triggers (all required)

The decommission PR is gated on every one of these going green in the 14-day window:

- [ ] Zero RDS-related Sentry exceptions for 7 consecutive days
- [ ] At least one Aerich migration run cleanly against RDS
- [ ] At least one OCPP simulator E2E test passed against RDS
- [ ] NR APM p95 latency within ~10% of pre-cutover baseline
- [ ] No CloudWatch RDS alarms triggered
- [ ] Backend restarted at least once without breaking

## Rollback path

For 14 days post-cutover, rollback is a 30-second operation:

1. Edit `.env.staging`: `POSTGRES_HOST=postgres` (Docker network name)
2. `$(STAGING_COMPOSE) restart backend`
3. Backend now talks to Docker postgres again. Original data intact (never deleted).

## Issues

See `issues/` for the breakdown:

- `01-provision-rds-staging.md` — AWS-side resource creation
- `02-backend-tls-and-dsn-changes.md` — Code changes for SSL + DSN
- `03-compose-and-env-changes.md` — Compose + `.env.staging.example` + Makefile
- `04-app-user-and-trial-restore.md` — Post-provisioning SQL + dry run
- `05-cutover-runbook.md` — The actual T-0 procedure (ready-for-human)
- `06-doc-and-memory-updates.md` — `reference_aws_ssm_protocol.md`, `CLAUDE.md`, `docs/v1/*`
- `07-decommission-docker-postgres.md` — Separate PR after 14-day validation window

## Lessons learned (post-cutover, 2026-05-27)

### What broke

**The entrypoint pre-flight DB check was missed in issue 02.** `database.py` and `tortoise_config.py` correctly used the new `db_ssl.get_ssl_config()` helper, but `backend/docker-entrypoint.sh` had its own inline `asyncpg.connect(..., ssl='disable')` that didn't. When Phase 4 of the cutover restarted the backend with `DB_HOST=<RDS>` and `DB_SSL_MODE=verify-full`, the entrypoint failed 30/30 connect attempts (RDS rejects non-TLS), exited 1, and the container restart-looped without ever reaching uvicorn. The health endpoint stayed `FAIL` for ~5 min of bonus downtime while I diagnosed and pushed a fix.

The fix landed in a follow-up commit that imports the same `db_ssl.get_ssl_config()` helper into the entrypoint's pre-flight loop. Now all three DB-connect call sites (runtime, Aerich, entrypoint) share the same SSL configuration logic.

Codified as feedback memory `feedback_check_entrypoint_during_db_config_changes`: **any time you change DB connection config, grep the repo for ALL `asyncpg.connect` / `psycopg.connect` / `pg_isready` / `psql -h` call sites, not just the obvious runtime DSN file.**

### What went well

- **The verify-full TLS path worked first try** in `database.py` / `tortoise_config.py`. The CA bundle baked into the image at `/etc/ssl/rds-ca-bundle.pem` and the `get_ssl_config()` helper returning a configured `SSLContext` was the right shape.
- **Phase 3 row-count parity** caught zero issues — the post-stop snapshot was perfectly consistent. The PRD's "stop backend first, then dump" sequencing kept the dump frozen.
- **Rollback was real and tested.** `.env.staging.pre-rds-cutover` + Docker postgres still running meant we always had a sub-minute fallback path. We never had to use it, but knowing it was there changed the risk calculus.
- **The `DROP OWNED BY ocpp_staging CASCADE` cleanup pattern** worked elegantly for resetting trial state without needing master-user `DROP DATABASE` (which RDS doesn't allow across owners).
- **The 14-day validation window is intact.** Docker postgres still running, no RDS rollback used. Issue 07 decommission is unaffected.

### Operational notes for prod (don't re-discover these)

- **RDS provisioning took ~20 min**, not the typical 5-10. Performance Insights + CloudWatch Logs export add steps. Provision well before any cutover window. Don't bundle provisioning into the maintenance window itself.
- **RDS landed in `ap-south-1c`** (cross-AZ from EC2's `ap-south-1a`). Adds ~1ms per query — invisible in OCPP workflows, but if you want same-AZ for any future read-heavy work, you can pin via `--availability-zone`. For Single-AZ, AWS picks; for Multi-AZ, primary placement is hint-able.
- **AWS SSM `AWS-RunShellScript` uses POSIX sh, not bash.** Parens in `echo` strings explode (`syntax error near unexpected token (`). Process substitution `source <(...)` fails the same way. Use `grep|cut` instead of source-ing dotenv files. Codified in `reference_aws_ssm_protocol`.
- **The cutover dump was 469MB** (vs 486MB live DB) — `pg_dump` is roughly 1:1 with data for our schema. Plain SQL format restored in ~3 min. Custom `-F c` format is unnecessary at this scale.
- **`make staging-deploy` does `git reset --hard origin/develop`.** If you need ad-hoc edits on the EC2 host, they'll be wiped on the next deploy. Always commit + push first.
- **Final downtime was ~9 min**: Phase 1 (~1 min) + Phase 2 (~3 min) + Phase 3 (~10s) + Phase 4 failed/recovery (~5 min). Without the entrypoint bug, would have been ~4 min. **Budget 15-20 min of staging-side downtime for prod**, accounting for any analogous "missed call site" surprise.

### What I'd do differently next time

1. **Grep for all DB-connect call sites BEFORE Phase 4.** Before flipping `.env`, run `grep -rn "asyncpg.connect\|psycopg.connect\|pg_isready\|psql -h" --include="*.sh" --include="*.py" backend/` and confirm every hit honors the new SSL config.
2. **Pre-warm RDS provisioning.** Start it a day before, not as Phase 1 of the cutover sequence.
3. **Add a smoke test against RDS that mimics the entrypoint** to issue 04's pre-flight checks: `docker run ... backend-image:latest /app/docker-entrypoint.sh --dry-run` or equivalent. Would have caught the SSL gotcha before Phase 4.
4. **Run the OCPP simulator post-cutover as a hard gate**, not as a "want to do later" item. We verified heartbeats land on RDS via the `log` table grow, but the full Start → MeterValues → Stop cycle wasn't exercised before declaring done.
