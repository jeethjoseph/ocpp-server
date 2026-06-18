Status: ready-for-human

# Merge `develop → deploy` and run `make prod-deploy`

## What to build

The actual deploy event. Force-push `origin/develop` to `origin/deploy`, then run `make prod-deploy` on the prod EC2 host. This triggers a `git fetch && git reset --hard origin/deploy`, then `docker compose up -d --build --force-recreate`, which:

1. Rebuilds the backend image (CA bundle, new Python deps including newrelic 13.0.1, new code)
2. Rebuilds the frontend image (Sentry source-map upload during build, new pages, etc.)
3. Recreates all containers
4. Entrypoint runs `aerich upgrade` → applies migrations 23-42 in sequence against Docker postgres
5. Uvicorn starts, OCPP WebSocket listener comes up
6. Healthcheck endpoint goes from `starting` → `healthy`

**Expected downtime**: 5-10 min for backend + frontend rebuild + migration train. Existing OCPP WebSocket sessions disconnect at recreate; chargers reconnect automatically per their normal retry logic.

**This is human-attended.** Migrations 27, 32, 33, 36 are the highest-risk. Watch logs in a separate terminal. Don't queue this on a flight.

## Prerequisites (must all be done)

- [ ] Issue 01 complete — both S3 buckets exist + IAM attached
- [ ] Issue 02 complete — all REQUIRED env vars set in `.env.prod`
- [ ] Issue 03 complete — pre-deploy `pg_dump` saved
- [ ] Free 60 min of attentive operator time
- [ ] No active high-impact charging sessions (check `/api/admin/transactions?status=RUNNING`)
- [ ] Maintenance window announced if applicable

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Tag a release first, then merge | Project doesn't use release tags. Workflow is force-push `origin/develop → origin/deploy`. Don't change the workflow in the middle of a deploy. |
| Cherry-pick commits rather than full merge | All 8 commits are dependent or thematically related. Splitting adds work and risk. |
| Blue-green deploy with a second EC2 | Not how this infra is set up. Real fix is RDS prod migration (separate event). |
| Skip `--force-recreate` to keep containers warm | New env vars and image rebuilds require `--force-recreate` to take effect. Project's standard pattern. |

## What to do

### 1. Local: push develop to deploy

```bash
# From your laptop, on the develop branch (or after fetching latest):
git fetch origin
git checkout develop
git pull origin develop
git push origin develop:deploy --force
# OR equivalently: make prod-push
```

### 2. SSM into prod EC2

```bash
make prod-ssm
```

### 3. On prod EC2: run the deploy

```bash
cd /home/ec2-user/ocpp-server

# Open backend logs in a SEPARATE SSM session BEFORE running the deploy:
# In that other window: sudo docker logs ocpp-backend-prod -f --tail=0
# (After deploy starts, the new container will replace the old one — switch to:
#  sudo docker logs ocpp-backend-prod -f --tail=200 once the new container is up)

# Trigger the deploy:
make prod-deploy
```

What you'll see (rough timeline):

```
Pulling from origin/deploy...
git fetch origin
git reset --hard origin/deploy
Updated to origin/deploy

[building images — 3-5 min, especially frontend]
[recreating containers]

# In the backend log window, watch for:
# - "Waiting for database..." (entrypoint pre-flight; should connect on attempt 1-2)
# - "Database is ready!"
# - "Running database migrations..."
# - Lines per migration: "23_20260429075904_add_kyc_fields", etc.
# - PARTICULAR attention on migration 33:
#     "NOTICE:  Migration 33: normalized X CHARGE_DEDUCT rows"
#     "NOTICE:  Migration 33: captured X adjustment rows"
#     If these counts look way off, STOP and roll back. Otherwise proceed.
# - "Migrations completed successfully."
# - "Starting OCPP Backend..."
# - "Starting with New Relic APM..." (because NEW_RELIC_MONITOR_MODE=true)
# - "Database initialized with Tortoise ORM"
# - "✅ New Relic APM: ENABLED"
# - "✅ Sentry Error Tracking: ENABLED"
# - "OCPP Central System API started"
```

If any migration step shows a Postgres ERROR — STOP. Don't re-run. Go to rollback. See issue 03 for the dump file path.

### 4. Wait for healthy

```bash
# In an SSM session on the host:
sudo docker ps --filter name=ocpp-backend-prod --format "table {{.Names}}\\t{{.Status}}"
# Should show: Up XX seconds (healthy) — note healthcheck has start_period=40s

curl -sf https://app.voltlync.com/health
# Should return 200 with database + redis both healthy
```

Total expected time from `make prod-deploy` start to backend `(healthy)`: **5-10 minutes**.

## Rollback procedure

If migrations fail OR backend won't start cleanly:

```bash
# 1. Stop the broken backend
sudo docker compose -f docker-compose.prod.yml --env-file .env.prod stop backend

# 2. Restore the pre-deploy DB
DB_USER=$(grep ^DB_USER= .env.prod | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME= .env.prod | cut -d= -f2-)
DB_PASSWORD=$(grep ^DB_PASSWORD= .env.prod | cut -d= -f2-)

# Drop and recreate the prod DB inside the postgres container
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

# Restore the pre-deploy dump
cat /home/ec2-user/ocpp-server/backups/prod_pre_deploy_2026-05-27.sql \
  | sudo docker exec -i ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME"

# 3. Revert the code on prod
git push origin 065460b:deploy --force          # FROM YOUR LAPTOP
# Then on prod EC2:
make prod-deploy
# This pulls the old commit + rebuilds with the old image + old migrations are already applied (they match)
```

Rollback total time: ~30-40 min depending on dump size + rebuild time.

## Verification (the basics — issue 05 has the full check)

- Backend container is up and `(healthy)`
- `https://app.voltlync.com/health` returns 200 with database + redis healthy
- `sudo docker logs ocpp-backend-prod 2>&1 | grep -E "Migrations completed|New Relic APM|Database initialized"` shows all three lines
- No `ERROR` or `FATAL` lines in the last 5 min of logs
- Aerich version on prod matches what we expect:
  ```bash
  sudo docker exec ocpp-backend-prod aerich heads
  # Should show 42_20260527070319_add_charger_availability.py
  ```

## Definition of done

- All migrations 23-42 applied (verified via `aerich heads`)
- Backend container `(healthy)`
- Health endpoint returns 200
- No error/fatal log lines since deploy start
- `OCPP-Server-Production` entity appearing in NR APM with traffic flowing
- Sentry receiving events at the `production` environment tag
- Issue 05 (post-deploy verification) ready to start
