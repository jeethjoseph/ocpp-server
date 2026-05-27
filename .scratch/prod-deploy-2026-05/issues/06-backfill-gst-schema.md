Status: ready-for-human

# Run `backfill_gst_schema.py` on prod

## What to build

Run the GST schema backfill script that completes what migrations 27 + 28 couldn't do (because they can't read env vars or do multi-table joins). The script handles 12 categories of fields on the `gst_invoice` table: place-of-supply state code (via station join), transaction_amount, energy_taxable_value, gateway_charges, GST splits, HSN code corrections, supplier identity (from env vars), tariff HSN code.

**Default: dry-run.** Apply only after reviewing the dry-run output.

## Prerequisites

- [ ] Issue 05 complete — deploy verified, migrations applied
- [ ] `VOLTLYNC_GSTIN` is non-empty in `.env.prod` (script uses this for supplier_gstin field)
- [ ] `VOLTLYNC_ADDRESS` is non-empty (used for supplier_address)
- [ ] An attentive operator with prod write authority — `--apply` modifies invoice rows

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Skip the backfill — accept the partial state | `supplier_gstin` is required for GST invoices to be legally valid. Without backfill, old invoices have NULL there and can't be reissued or audited. |
| Run `--apply` without dry-run | Modifies invoice rows in place. Even though it's idempotent (re-runnable), getting bad data in is harder to recover from than reviewing first. |
| Backfill via direct SQL | Script handles multi-table joins (txn → charger → station for state code) that are tedious to express inline. Use the script. |

## What to do

### 1. Dry-run

```bash
# SSM into prod EC2:
sudo docker exec ocpp-backend-prod python -m scripts.backfill_gst_schema --dry-run 2>&1 | tee /tmp/gst-backfill-dryrun.log
```

Read the output. Expected to show:
- Number of `gst_invoice` rows to update per field
- Sample rows showing what values will be set
- Any rows it can't process (e.g. invoice with no linked transaction) — these need manual investigation

### 2. Sanity-review the dry-run

- Does the count of rows match what you'd expect for prod's invoice history?
- Do the supplier_gstin / supplier_address values in the output match what's in `.env.prod`?
- Are there any "skipping row X — no linked txn" warnings? Note those for follow-up.
- HSN code corrections show `previous_value=null → new_value='996749'` (or similar)

If anything looks wrong, STOP and investigate before --apply.

### 3. Apply

```bash
sudo docker exec ocpp-backend-prod python -m scripts.backfill_gst_schema 2>&1 | tee /tmp/gst-backfill-apply.log
```

(The script takes no flag for apply — `--dry-run` is the opt-in dry mode; running without it commits.)

Look for the summary line at the end: how many rows updated per field.

### 4. Verify

```bash
DB_USER=$(grep ^DB_USER= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)

# Spot-check: pick the most recent invoice and verify the new fields are populated
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -x -c "
  SELECT id, invoice_number, supplier_gstin, supplier_name, place_of_supply_state_code,
         series, financial_year, hsn_sac_code, gst_rate_percent
  FROM gst_invoice ORDER BY id DESC LIMIT 1;
"

# Aggregate: count of rows still missing the critical fields (should be 0 or near-0)
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT
    COUNT(*) FILTER (WHERE supplier_gstin IS NULL OR supplier_gstin = '') AS missing_supplier_gstin,
    COUNT(*) FILTER (WHERE hsn_sac_code IS NULL) AS missing_hsn,
    COUNT(*) FILTER (WHERE place_of_supply_state_code IS NULL) AS missing_state_code
  FROM gst_invoice;
"
```

Expected: zero or very few missing values. Some rows might legitimately not have a state code (invoices generated before the station data was populated) — those go in the manual-follow-up bucket.

## Definition of done

- Dry-run completed cleanly + output reviewed
- Apply completed cleanly + summary line shows expected row counts
- Spot-check verifies fields populated correctly on a sample invoice
- Aggregate check shows zero or near-zero missing values for critical fields
- Any manual-follow-up rows from the dry-run are documented somewhere outside this issue
- `/tmp/gst-backfill-apply.log` captured for forensics
