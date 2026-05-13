# GST Billing — Deploy & Rollback Runbook

**Branch:** `65-franchisee-ownership-module` (or whichever branch carries migrations 27 + 28)
**Last updated:** 2026-05-13
**Owner:** whoever is on deploy duty

This runbook covers the deploy of the GST invoice schema overhaul:

- Migration 27 — schema cleanup (drops cancellation/credit-note infra, adds `gst_rate_percent` / `place_of_supply_state_code` / `series` / `financial_year`, fixes HSN default, replaces global UNIQUE with partial indexes)
- Migration 28 — supplier-always-VoltLync correction (drops `gst_invoice_counter.franchisee_id`, renumbers existing invoices to gapless `VL/{SERIES}/{FY}/{SEQ:05d}`, normalizes supplier identity)
- Migration 29 — franchisee-as-substore (re-adds counter `franchisee_id`, adds `franchisee_*` snapshot columns + `refund_amount` to `gst_invoice`, re-renumbers per-(franchisee, series, FY), backfills snapshot fields from live `franchisee` table). Per Razorpay's payer-payee transparency rule.
- New S3-backed PDF storage (`services/s3_service.py`, lazy upload on first download)
- New admin "GST Filings" page at `/admin/gst-filings`
- One-off backfill script for data the migrations can't express in SQL alone

This deploy is **riskier than most** because migration 28 permanently rewrites `invoice_number` and `supplier_*` fields on every existing row. Read the rollback section before you run anything.

---

## 0. One-time S3 prerequisites

PDFs are uploaded to S3 lazily on first download. The list view and CSV export work without S3, but PDF links will 500. Set this up once per environment, before anyone clicks a PDF link.

```bash
# From your laptop (or any machine with AWS creds)
export AWS_PROFILE=voltlync
export REGION=ap-south-1
export BUCKET=voltlync-invoices-staging          # voltlync-invoices-prod for prod

# Create the bucket, block public access, enable AES256 encryption
aws s3api create-bucket --bucket $BUCKET --region $REGION \
  --create-bucket-configuration LocationConstraint=$REGION
aws s3api put-public-access-block --bucket $BUCKET \
  --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws s3api put-bucket-encryption --bucket $BUCKET \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# CORS — REQUIRED so the frontend's authenticated fetch can follow the
# 302 redirect to the presigned S3 URL. Without this, browsers see no
# Access-Control-Allow-Origin on the S3 response and the fetch() throws
# "Failed to fetch". Allow all three deploy origins:
aws s3api put-bucket-cors --bucket $BUCKET --cors-configuration '{
  "CORSRules": [{
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": [
      "https://staging.voltlync.com",
      "https://app.voltlync.com",
      "http://localhost:3000"
    ],
    "ExposeHeaders": ["ETag", "Content-Disposition", "Content-Length"],
    "MaxAgeSeconds": 3600
  }]
}'

# Find the EC2 instance role
aws ec2 describe-instances --instance-ids i-00fd9fb3c2b48932a \
  --query "Reservations[0].Instances[0].IamInstanceProfile.Arn" --output text
# Note the role name from the end of the ARN

# Attach an inline policy granting S3 read/write on this bucket only
aws iam put-role-policy --role-name <ROLE_NAME> \
  --policy-name VoltlyncInvoicesS3Access \
  --policy-document file://<(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject"],
    "Resource": "arn:aws:s3:::$BUCKET/*"
  }]
}
EOF
)
```

Verify from inside the backend container post-deploy:

```bash
docker exec ocpp-backend python -c "from services import s3_service; print(s3_service._bucket())"
# Expect: voltlync-invoices-staging
```

---

## 1. Env-var prerequisites

The deploy will **fail open** (no new invoices issued) if `VOLTLYNC_GSTIN` is empty post-deploy. Add these to `.env.staging` on the EC2 **before** running `make staging-deploy`.

```ini
# VoltLync supplier identity (REQUIRED — generate_invoice aborts when GSTIN is empty)
VOLTLYNC_BUSINESS_NAME=VOLTLYNC PRIVATE LIMITED
VOLTLYNC_GSTIN=32XXXXXXXXXXXZ5          # actual 15-char GSTIN
VOLTLYNC_ADDRESS=<registered office address>
VOLTLYNC_STATE=Kerala
VOLTLYNC_STATE_CODE=32                  # 2-digit GST state code (NOT "KL")

# Invoice PDF persistence
AWS_REGION=ap-south-1
AWS_S3_INVOICE_BUCKET=voltlync-invoices-staging
```

No AWS access keys — boto3 picks up the EC2 instance role credentials automatically.

---

## 2. Pre-deploy safety net

Run these **immediately before** `make staging-deploy`. Together they're the only thing that makes a full rollback possible.

```bash
# On the EC2 via `make staging-ssm`, then:
cd /home/ec2-user/ocpp-server

# A. Capture the current commit hash — this is your code rollback target
git rev-parse origin/develop | tee /tmp/staging-rollback-commit.txt
# (Write this hash down somewhere outside the EC2 too)

# B. Snapshot the database — the only true rollback for migration 27+28's data changes
make staging-backup-db
ls -lh backups/staging_backup_*.sql | tail -1
# Confirm size > 0 (current staging DB ~10-50 MB depending on log volume)
```

The backup is plain SQL via `pg_dump`, restored with `psql` (see rollback section).

---

## 3. Deploy steps

```bash
# From your laptop
make staging-push                       # force-push HEAD → origin/develop

# SSM in
make staging-ssm
cd /home/ec2-user/ocpp-server

# Pre-flight (see section 2)
git rev-parse origin/develop | tee /tmp/staging-rollback-commit.txt
make staging-backup-db

# Deploy
make staging-deploy                     # pull develop, rebuild backend+frontend, recreate containers
make staging-migrate                    # apply migrations 27 + 28 in sequence
docker exec ocpp-backend python scripts/backfill_gst_schema.py --dry-run
# review the dry-run output, then for real:
docker exec ocpp-backend python scripts/backfill_gst_schema.py
```

**Two distinct scripts run on staging:**

| Script | Run via | Does |
|---|---|---|
| `aerich upgrade` | `make staging-migrate` | Applies migrations 27, 28, **and 29** in sequence. Includes inline SQL renumbering (twice — flat in 28, per-franchisee in 29), supplier normalization, franchisee snapshot backfill, counter rebuild, and refund/gross split restoration. |
| `backfill_gst_schema.py` | `docker exec ocpp-backend python scripts/...` | Fills `place_of_supply_state_code` from station, recomputes taxable/tax/total from stored `txn.energy_charge`/`qr_payment.razorpay_*`, restores gross `transaction_amount = amount_paid` + explicit `refund_amount`, sets `supplier_gstin`/`supplier_address` and `franchisee_*` snapshot fields from env vars and the live franchisee table. |

The backfill script is idempotent — safe to re-run if needed.

---

## 4. Post-deploy verification

### 4a. Schema sanity (run on EC2)

```bash
docker compose -f docker-compose.staging.yml exec -T postgres \
  sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "
    SELECT series, COUNT(*),
           MIN(invoice_number) AS first, MAX(invoice_number) AS last,
           COUNT(DISTINCT supplier_name) AS distinct_suppliers,
           SUM(total_amount) AS sum_total
    FROM gst_invoice GROUP BY series ORDER BY series;
  "'
```

Expected post-deploy: `distinct_suppliers = 1` for every series, gapless invoice numbers `VL/{SERIES}/202627/00001..00N` per series.

### 4b. Counter shape

```bash
docker compose -f docker-compose.staging.yml exec -T postgres \
  sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\\d gst_invoice_counter"'
```

Expected: no `franchisee_id` column, unique index on `(series, financial_year)`.

### 4c. S3 wired up

```bash
docker exec ocpp-backend python -c "from services import s3_service; print(s3_service._bucket())"
# Expect: voltlync-invoices-staging  (NOT empty, NOT a RuntimeError)
```

### 4d. Browser smoke test

1. Open `https://staging.voltlync.com/admin/gst-filings` — confirm 4 summary cards populate, table shows ~28 rows.
2. Filter by Series = "QR" — count should drop to ~21.
3. Filter by Inter-state = "Inter-state (IGST)" — depends on staging data, but if any row has `place_of_supply_state_code != "32"`, it shows up here.
4. Click "Export CSV" — downloads `gst_invoices_all_<date>.csv`. Open in a spreadsheet; first column is `invoice_number`, every supplier column says `VOLTLYNC PRIVATE LIMITED`.
5. Click any "PDF" link — first click does an S3 PUT (~1-2s), opens the PDF. Click again — instant.

### 4e. Verify a new session issues an invoice end-to-end

Drive a real charging session (or trigger one via the admin remote-start endpoint) and confirm a `gst_invoice` row appears with the next sequence number in its series. If the session completes but no invoice appears, check the backend logs for `GST invoice NOT issued for txn N: VOLTLYNC_GSTIN not configured` — that means env vars didn't get picked up by the running container.

---

## 5. Rollback procedures

### Decision tree

| Symptom | Path | Time |
|---|---|---|
| Env-var typo / wrong S3 bucket / GSTIN wrong | **Forward-fix** (5a) | ~1 min |
| New code crashes, but `make staging-migrate` has NOT run yet | **Code-only** (5b) | ~5 min |
| Anything went wrong **after** `make staging-migrate` | **Full restore** (5c) | ~5 min |
| Just want pre-deploy state exactly | **Full restore** (5c) | ~5 min |

The cutoff for code-only vs full restore is `make staging-migrate`. After that, the old code cannot start — it references columns and tables the new schema doesn't have.

### 5a. Forward-fix (env / config)

Most common case. Migration succeeded, app is running, but something's wrong with config.

```bash
# On EC2
cd /home/ec2-user/ocpp-server
nano .env.staging                          # fix the value
make staging-restart                       # `up -d` re-reads --env-file
```

If the issue is the S3 bucket name or IAM policy, fix it in AWS (or `aws iam put-role-policy`), then `make staging-restart` so boto3 picks up any refreshed credentials.

### 5b. Code-only rollback (DB is fine)

Only safe **before** migrations 27+28 have been applied — otherwise old code will crash on startup. Use this if `make staging-deploy` succeeded but you didn't run `make staging-migrate` yet, or if the migration's already been rolled back via 5c.

```bash
# From your laptop
git push origin <rollback-commit-hash>:develop --force

# SSM in
make staging-ssm
cd /home/ec2-user/ocpp-server
make staging-deploy                        # rebuild with old code
```

### 5c. Full restore (code + DB)

The reliable one. Brings staging back to bit-for-bit pre-deploy state. Now a single Make target.

```bash
# On the EC2
cd /home/ec2-user/ocpp-server

# 1. Restore the DB from the newest dump (stops backend+frontend, drops+recreates DB,
#    loads dump, restarts). Pass DUMP=backups/specific_file.sql to pick a non-newest dump.
make staging-restore-db

# 2. Revert code to the rollback commit (from your laptop)
git push origin <rollback-commit-hash>:develop --force

# 3. Back on the EC2 — rebuild + restart with the old code
make staging-deploy
```

After this completes, staging is identical to pre-deploy: original `invoice_number` strings, original `supplier_*` fields, cancellation columns + `gst_credit_note` table back, `gst_invoice_counter.franchisee_id` back. The S3 bucket (if you created one) is fine to leave — it'll just have orphan PDF keys that no row references.

### What you cannot roll back

- **Orphan S3 PDFs.** Once a PDF is uploaded under the new key scheme, the S3 object stays after a DB rollback. The pre-deploy DB has `pdf_url = NULL` on every row so nothing breaks. Cleanup is optional: `aws s3 rm s3://voltlync-invoices-staging/invoices/ --recursive`.
- **Inflight invoices issued under the new code.** Any session that completed between deploy and rollback got an invoice with the new numbering. Those go away on DB restore — the underlying transaction record stays, and re-running the deploy later will re-issue with whatever the next sequence number is at that time.

---

## 6. Optional dress rehearsal

Worth doing the first time you run this deploy because migration 28 is destructive and tested against only the 8 stub rows locally. Costs ~10 minutes.

```bash
# From your laptop — copy the staging dump down
make staging-ssm
# inside SSM:
cat /home/ec2-user/ocpp-server/backups/staging_backup_<TIMESTAMP>.sql
# (copy to clipboard, or scp it down)

# Back on your laptop — load it into local postgres (wipes local DB)
docker exec -i ocpp-postgres bash -c 'psql -U $POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS ocpp_db;"'
docker exec -i ocpp-postgres bash -c 'psql -U $POSTGRES_USER -d postgres -c "CREATE DATABASE ocpp_db OWNER $POSTGRES_USER;"'
docker exec -i ocpp-postgres psql -U ocpp_user -d ocpp_db < /path/to/staging_backup.sql

# Run the migrations + backfill against the snapshot
docker exec ocpp-backend aerich upgrade
docker exec -e VOLTLYNC_GSTIN=<real-staging-gstin> \
            -e VOLTLYNC_ADDRESS="<real address>" \
            ocpp-backend python scripts/backfill_gst_schema.py

# Inspect the renumbered/normalized rows
docker exec -i ocpp-postgres bash -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -c "
  SELECT series, COUNT(*), MIN(invoice_number), MAX(invoice_number)
  FROM gst_invoice GROUP BY series;
"'
```

If the result looks right (21 QR + 7 WAL, gapless, all VoltLync supplier), the real staging deploy will produce the same outcome.

---

## 7. Prod deploy

Same shape, swap "staging" for "prod" everywhere:

- `make prod-push` / `make prod-deploy` / `make prod-migrate` / `make prod-backup-db`
- Edit `.env.prod` on the prod EC2 (different instance ID, different IAM role)
- S3 bucket: `voltlync-invoices-prod`
- Rollback uses `prod_backup_<TIMESTAMP>.sql`

The dress rehearsal is **doubly** worth doing for prod — use the prod dump in a local DB and confirm output before deploying.

---

## 8. Known follow-ups (not blocking)

- ~~**`make staging-restore-db` / `make prod-restore-db` targets**~~ — done. Step 5c is now a single command.
- **S3 lifecycle rules** — move objects to `STANDARD_IA` after 90d, `GLACIER` after 1y. Required for the 6-year CGST Rule 56 retention. Not blocking deploy.
- **Tag the rollback commit** — `git tag pre-gst-billing-deploy <hash>` before deploy gives a named reference instead of a hash. Optional.

---

## Quick-reference: minimum command set

```bash
# Pre-deploy
make staging-backup-db
git rev-parse origin/develop > /tmp/staging-rollback-commit.txt

# Deploy
make staging-deploy
make staging-migrate
docker exec ocpp-backend python scripts/backfill_gst_schema.py

# Rollback (full)
docker compose -f docker-compose.staging.yml --env-file .env.staging stop backend frontend
docker compose -f docker-compose.staging.yml --env-file .env.staging exec -T postgres sh -c \
  'psql -U $POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DB; CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER;"'
docker compose -f docker-compose.staging.yml --env-file .env.staging exec -T postgres sh -c \
  'psql -U $POSTGRES_USER -d $POSTGRES_DB' < backups/staging_backup_<TIMESTAMP>.sql
git push origin <rollback-hash>:develop --force
make staging-deploy
```
