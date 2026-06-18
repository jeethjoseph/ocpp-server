Status: ready-for-human

# Create app user + database on RDS, then dry-run dump + restore

## What to build

Two phases of pre-cutover work that prove the migration is mechanically sound, before we actually take staging downtime:

1. **One-time SQL setup** as the master user on the new RDS instance: create the app user (`ocpp_staging`), create the app database (`ocpp_staging_db`), and grant ownership
2. **Trial dump + restore**: dump from live Docker postgres into RDS, verify row counts match, then **delete the trial data so the cutover restores from a clean state**

Both phases are no-impact on the live staging backend.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Skip the trial restore, dump + restore directly during cutover | We've never restored to this RDS instance. A first-try restore during cutover is exactly when you discover a permissions, version, or connectivity issue. Trial-run finds these without taking downtime. |
| Trial-restore to a separate "scratch" RDS instance | Adds cost + provisioning. Same instance is fine because we drop the trial data before cutover. |
| Restore as master user, then `REASSIGN OWNED` | More steps with the same result. Restoring directly as the app user makes ownership correct from line 1. |
| Use `pg_dump -F c` (custom format) for parallel restore | Our 486MB DB restores in <30s single-threaded. Custom format adds complexity without benefit at this size. |
| Skip cleanup after trial | Cutover restore against non-empty DB will conflict — every `CREATE TABLE` becomes `... already exists`. Plain restore needs an empty DB. |

## What to do

Prerequisite: issue 01 complete (RDS instance available), endpoint hostname known.

### Phase A — Create app user + database

From staging EC2 (`make staging-ssm`), running as master user:

```bash
ENDPOINT=ocpp-staging-db.cXXXXXXX.ap-south-1.rds.amazonaws.com  # actual from issue 01
APP_PW=$(openssl rand -base64 32 | tr -d '/=+')
echo "App user password (will go into .env.staging at cutover): $APP_PW"
# Store this securely. Will be needed at cutover time.

PGPASSWORD='<master-password-from-issue-01>' \
  psql -h "$ENDPOINT" -U ocpp_admin -d postgres <<SQL
CREATE USER ocpp_staging WITH PASSWORD '$APP_PW';
CREATE DATABASE ocpp_staging_db OWNER ocpp_staging;
GRANT ALL PRIVILEGES ON DATABASE ocpp_staging_db TO ocpp_staging;
\\c ocpp_staging_db
GRANT ALL ON SCHEMA public TO ocpp_staging;
SQL
```

Verify:

```bash
PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" -U ocpp_staging -d ocpp_staging_db \
  -c "SELECT current_user, current_database();"
# Expected: ocpp_staging | ocpp_staging_db
```

### Phase B — Trial dump + restore

Still no impact on live backend; we're reading from Docker postgres and writing to a separate RDS instance.

```bash
# Dump from Docker postgres (live, but read-only operation)
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p ~/ocpp-server/backups
sudo docker exec ocpp-postgres-staging pg_dump \
  -U ocpp_staging \
  --clean --if-exists \
  --no-owner --no-acl \
  ocpp_staging_db > ~/ocpp-server/backups/staging_trial_$TS.sql

# Inspect size
ls -lh ~/ocpp-server/backups/staging_trial_$TS.sql
# Expected: ~150-200 MB plain SQL

# Restore as app user (so future objects are owned correctly)
PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" \
  -U ocpp_staging -d ocpp_staging_db \
  --set ON_ERROR_STOP=on \
  < ~/ocpp-server/backups/staging_trial_$TS.sql
# Watch for errors. Expected output: lots of "CREATE TABLE", "ALTER TABLE", etc.
```

### Phase C — Verify row counts

Compare counts between Docker postgres (source) and RDS (target):

```bash
TABLES="log signal_quality charger_error meter_value audit_log \
        transaction qr_payment commission_ledger_entry wallet_transaction \
        aerich"

for t in $TABLES; do
  SRC=$(sudo docker exec ocpp-postgres-staging psql -U ocpp_staging -d ocpp_staging_db \
        -tAc "SELECT COUNT(*) FROM $t;")
  DST=$(PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" -U ocpp_staging -d ocpp_staging_db \
        -tAc "SELECT COUNT(*) FROM $t;")
  if [ "$SRC" = "$DST" ]; then
    printf "  %-30s OK     (%s)\n" "$t" "$SRC"
  else
    printf "  %-30s MISMATCH (src=%s dst=%s)\n" "$t" "$SRC" "$DST"
  fi
done
```

All tables must show OK. If any MISMATCH, investigate before proceeding to cutover.

### Phase D — Verify Aerich state

```bash
PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" -U ocpp_staging -d ocpp_staging_db \
  -c "SELECT version, app FROM aerich ORDER BY id DESC LIMIT 5;"
```

Should show the most recent migration that was applied to Docker postgres. Confirms migration history is intact.

### Phase E — Clean up trial data

This is **critical** — the cutover restore needs a clean target DB.

```bash
PGPASSWORD='<master-password>' psql -h "$ENDPOINT" -U ocpp_admin -d postgres <<SQL
DROP DATABASE ocpp_staging_db;
CREATE DATABASE ocpp_staging_db OWNER ocpp_staging;
\\c ocpp_staging_db
GRANT ALL ON SCHEMA public TO ocpp_staging;
SQL
```

Verify it's empty:

```bash
PGPASSWORD="$APP_PW" psql -h "$ENDPOINT" -U ocpp_staging -d ocpp_staging_db \
  -c "\\dt"
# Expected: "Did not find any relations."
```

## What to record before moving to the cutover issue

After Phases A-E complete:

- [ ] App user password (`$APP_PW`) — store in password manager; will be set in `.env.staging` at cutover
- [ ] RDS endpoint hostname — confirmed reachable from EC2
- [ ] Trial restore succeeded with zero errors
- [ ] All row counts matched between Docker postgres and RDS
- [ ] Aerich version on RDS matches Docker postgres
- [ ] Trial data dropped; RDS DB is now empty

## Definition of done

- App user + app database created on RDS, app user owns the DB
- Trial dump + restore completed end-to-end with no errors
- Row counts match across all critical tables
- Trial data cleaned up; RDS DB is empty and ready for the cutover restore
- App user password is stored safely outside of chat/git
