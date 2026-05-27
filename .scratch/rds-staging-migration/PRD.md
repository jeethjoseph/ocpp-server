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
