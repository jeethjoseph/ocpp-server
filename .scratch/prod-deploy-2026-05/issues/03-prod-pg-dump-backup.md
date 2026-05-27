Status: ready-for-agent

# Pre-deploy `pg_dump` of prod Docker postgres

## What to build

A single full `pg_dump` of `ocpp_prod_db` from the live Docker postgres container on prod EC2, saved to `/home/ec2-user/ocpp-server/backups/prod_pre_deploy_2026-05-27.sql`. This is the rollback artifact for the entire deploy event — if migrations 23-42 do anything we don't like, or if backfills go wrong, the path back is `psql < this_file`.

No-impact operation. `pg_dump` is a read-only consistent snapshot; takes a few minutes; doesn't block the running backend.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Skip the backup; trust forward-only migrations | "Forward-only" doesn't help if a migration writes garbage into existing rows. Real recovery needs a known-good snapshot. |
| Take an EBS snapshot of the host disk | Crash-consistent only — Postgres recovery on restore takes minutes and may lose recent writes. `pg_dump` is a transaction-consistent logical snapshot. |
| Stream `pg_dump` directly to S3 | More moving parts. Local file on EC2 root disk is fine for one-off use (file gets deleted ~1 month later). |
| Use the existing `make prod-backup-db` Makefile target | That works too, but produces a timestamped filename in `backups/`. Using a named file we know is "the pre-deploy artifact" is cleaner. |

## What to do

```bash
# SSM into prod EC2 first via `make prod-ssm`, then on the host:

cd /home/ec2-user/ocpp-server
mkdir -p backups

# Read credentials from existing .env.prod (the file we just backed up in issue 02).
DB_USER=$(grep ^DB_USER= .env.prod | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME= .env.prod | cut -d= -f2-)

DUMP=/home/ec2-user/ocpp-server/backups/prod_pre_deploy_2026-05-27.sql

echo "Starting pg_dump at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
sudo docker exec ocpp-postgres-prod pg_dump \
  -U "$DB_USER" \
  --no-owner --no-acl --clean --if-exists \
  "$DB_NAME" > "$DUMP"
echo "Completed at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

ls -lh "$DUMP"
echo "Row counts in dump (sanity):"
grep -c "^COPY" "$DUMP"
```

Expected: a file in the 50-500 MB range (depends on real prod data). The `grep -c "^COPY"` line should show the count of tables data was dumped from — a positive integer.

## Verification

```bash
# Confirm dump is readable + has expected sentinel content
head -10 "$DUMP"
# Should show pg_dump header lines

tail -3 "$DUMP"
# Should show: -- PostgreSQL database dump complete

# Check schema completeness — count CREATE TABLE statements
grep -c "^CREATE TABLE" "$DUMP"
# Should match the number of tables in the live DB
```

Optional but recommended: spot-check a critical row count matches dump vs live DB. Example for `gst_invoice`:

```bash
LIVE_COUNT=$(sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT COUNT(*) FROM gst_invoice;")
DUMP_COUNT=$(grep -A 1000000 "COPY public.gst_invoice " "$DUMP" | sed -n '/^\\\\\\.$/q;p' | wc -l)
# DUMP_COUNT will be 1 less because the COPY header line isn't a data row
echo "Live: $LIVE_COUNT  Dump (approx): $DUMP_COUNT"
```

## What happens to this file

- **Lives on prod EC2 root disk** through the deploy + validation window
- **Stays around for 30 days post-deploy** as a forensic artifact (manual cleanup after that)
- **The actual rollback file**, if needed: `psql -U <user> -d <db> < /home/ec2-user/ocpp-server/backups/prod_pre_deploy_2026-05-27.sql`

If you want long-term archive, copy to S3 (the invoices bucket is fine — encryption is on, lifecycle goes to Glacier):

```bash
aws s3 cp "$DUMP" s3://voltlync-invoices-prod/_internal/db-backups/$(basename "$DUMP")
```

(The `_internal/` prefix keeps it organized away from real invoice paths.)

## Definition of done

- `prod_pre_deploy_2026-05-27.sql` exists in `/home/ec2-user/ocpp-server/backups/` on prod EC2
- File is non-empty (≥50 MB) and `pg_dump` output reports no errors
- `head` and `tail` of the file show expected `pg_dump` sentinels
- (Optional) Mirror copy uploaded to `s3://voltlync-invoices-prod/_internal/db-backups/`
- The path is recorded somewhere accessible for the deploy operator (e.g. in the deploy-thread Slack message)
