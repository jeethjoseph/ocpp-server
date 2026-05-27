Status: ready-for-human

# Cutover runbook: switch backend from Docker postgres to RDS

## What to build

The actual ~5-minute downtime window during which staging backend stops writing to Docker postgres and starts writing to RDS. This is a **manual, supervised** operation — not an agent task.

Prerequisites: issues 01-04 complete. RDS instance live, app user created, trial restore validated and cleaned up, backend image rebuilt with the CA bundle baked in.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Zero-downtime via DMS (CDC streaming) | 486MB DB doesn't justify the complexity. DMS adds days of setup for seconds of saved downtime. |
| Streaming pg_dump pipe directly to RDS (no file) | No artifact for forensics if restore fails halfway. File-based is the safer pattern. |
| Cutover during high-traffic window | Defeats the "minimize impact" goal. Pick a low-traffic IST window. |
| Restore as master user | Then need `REASSIGN OWNED` cleanup. Restoring as app user makes ownership correct from line 1. |

## Pre-cutover checklist (verify before T+0)

- [ ] Issue 02 PR merged (backend image has CA bundle, DSN supports SSL)
- [ ] Issue 03 PR merged (compose has no `depends_on: postgres` for backend; `staging-backup-db` warns)
- [ ] Backend Docker image rebuilt and pushed (`make staging-deploy` since the PRs landed)
- [ ] Issue 04 complete (RDS app user + DB exist; trial restore done; trial data cleaned)
- [ ] App user password (`$APP_PW`) accessible
- [ ] RDS endpoint hostname known
- [ ] Sentry + NR dashboards open in tabs
- [ ] OCPP simulator script ready to run post-cutover
- [ ] Maintenance announcement sent (if applicable)
- [ ] Calendar blocked, no concurrent deploys planned
- [ ] Low-traffic window confirmed (recommend 02:00-03:00 IST or similar)

## Cutover sequence (T+0 to T+5)

### T+0:00 — Open SSM session to staging EC2

```bash
make staging-ssm
cd ~/ocpp-server
```

Record start time in a notes file for the postmortem.

### T+0:30 — Stop backend (DB writes pause)

```bash
$(STAGING_COMPOSE) stop backend
sudo docker ps | grep ocpp-backend-staging  # expect empty
```

Docker postgres keeps running — it has no writes incoming.

### T+0:45 — Final pg_dump from Docker postgres

```bash
TS=$(date +%Y%m%d_%H%M%S)
sudo docker exec ocpp-postgres-staging pg_dump \
  -U ocpp_staging \
  --clean --if-exists \
  --no-owner --no-acl \
  ocpp_staging_db > backups/staging_cutover_$TS.sql

ls -lh backups/staging_cutover_$TS.sql
# Expected: ~150-200 MB
```

### T+1:30 — Restore to RDS

```bash
ENDPOINT=ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com  # from issue 01
APP_PW='<from-issue-04>'                                         # from password manager

PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" \
  -U ocpp_staging -d ocpp_staging_db \
  --set ON_ERROR_STOP=on \
  < backups/staging_cutover_$TS.sql 2>&1 | tee /tmp/cutover_restore_$TS.log

echo "Restore exit code: $?"  # expect 0
```

### T+2:30 — Row count parity check

```bash
TABLES="log signal_quality charger_error meter_value audit_log \
        transaction qr_payment commission_ledger_entry wallet_transaction aerich"

echo "Table parity check at $(date)"
for t in $TABLES; do
  SRC=$(sudo docker exec ocpp-postgres-staging psql -U ocpp_staging -d ocpp_staging_db \
        -tAc "SELECT COUNT(*) FROM $t;")
  DST=$(PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" -U ocpp_staging -d ocpp_staging_db \
        -tAc "SELECT COUNT(*) FROM $t;")
  status="OK"; [ "$SRC" = "$DST" ] || status="MISMATCH"
  printf "  %-30s %s  src=%s  dst=%s\n" "$t" "$status" "$SRC" "$DST"
done
```

**Abort if any MISMATCH.** Investigate before proceeding. Backend is still stopped; data is safe.

### T+3:00 — Update `.env.staging`

```bash
# Backup first
cp .env.staging .env.staging.pre-rds-cutover

# Edit. Replace:
#   POSTGRES_HOST=postgres
#   POSTGRES_PASSWORD=<old-docker-pw>
# With:
#   POSTGRES_HOST=ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com
#   POSTGRES_PASSWORD=<APP_PW from issue 04>
# Add:
#   POSTGRES_SSL_MODE=verify-full

# Verify the change
grep -E "^POSTGRES_" .env.staging
```

### T+3:30 — Restart backend with new env

```bash
$(STAGING_COMPOSE) up -d backend
# docker compose up -d re-reads .env.staging
```

### T+4:00 — Tier 1 mechanical validation

```bash
# Container is up
sudo docker ps | grep ocpp-backend-staging

# Backend is pointing at RDS
sudo docker exec ocpp-backend-staging printenv POSTGRES_HOST
# Expected: ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com

# No connection errors in last 60s of logs
sudo docker logs ocpp-backend-staging --since 60s 2>&1 | grep -iE "error|fatal|refused"
# Expected: empty or only benign warnings

# Health endpoint
curl -sf https://staging.voltlync.com/api/health
# Expected: 200 with healthy JSON
```

If any Tier 1 check fails → **immediate rollback** (next section).

### T+4:30 — Tier 2 functional validation

```bash
# A read endpoint that touches several tables
curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://staging.voltlync.com/api/admin/chargers | jq '.data | length'

# The slowest endpoint we identified in NR (regression check)
time curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://staging.voltlync.com/api/admin/chargers/1

# Aerich heads — migration history intact
sudo docker exec ocpp-backend-staging aerich heads
# Expected: same migration version as pre-cutover
```

### T+5:00 — Declare cutover complete (or rollback)

If all Tier 1 + Tier 2 checks pass: cutover is technically complete. Backend is now writing to RDS. Docker postgres remains alive but is no longer receiving writes.

Move to Tier 3 (behavioral) over the next 24 hours; see issue 06.

## Rollback procedure (any time post-T+3:30, within ~minutes)

If something is wrong and you need to revert:

```bash
# 1. Stop the broken backend
$(STAGING_COMPOSE) stop backend

# 2. Restore the previous env
cp .env.staging.pre-rds-cutover .env.staging

# 3. Restart backend (now pointing back at Docker postgres)
$(STAGING_COMPOSE) up -d backend

# 4. Verify recovery
sudo docker exec ocpp-backend-staging printenv POSTGRES_HOST  # expect: postgres
curl -sf https://staging.voltlync.com/api/health

# 5. Investigate RDS issue separately — RDS instance stays running but unused
```

Total rollback time: ~60 seconds. Docker postgres still has all the original data.

## Post-cutover (T+5 to T+1 hour)

- Watch backend logs for any unexpected errors
- Confirm a single OCPP heartbeat lands in RDS (signals chargers reconnecting):
  ```bash
  PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" -U ocpp_staging -d ocpp_staging_db \
    -c "SELECT MAX(timestamp) FROM log;"
  # Expected: a timestamp in the last few minutes
  ```
- Run the OCPP simulator E2E test against staging — confirms StartTransaction → MeterValues → StopTransaction works end-to-end on RDS

## Definition of done

- All Tier 1 + Tier 2 checks pass
- Backend is writing to RDS (verified via env var inspection)
- Docker postgres still running (rollback target for the validation window)
- Cutover dump file saved in `backups/`
- Cutover timestamp + outcome recorded for the postmortem / change log
