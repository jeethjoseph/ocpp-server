Status: ready-for-human

# Run `backfill_below_threshold.py` on prod

## What to build

One-shot backfill that flips stuck `PENDING` `commission_ledger_entry` rows with sub-floor `franchisee_payout` (`< MINIMUM_TRANSFER_AMOUNT`, default ₹1.00) into the new terminal status `BELOW_THRESHOLD`. These entries were created before the `BELOW_THRESHOLD` state existed in the enum (migration 25), so they got stuck as `PENDING` and the retry sweep silently ignored them.

Same pattern as staging — we ran this same script on staging to clear 5 sub-paise entries.

**Default: dry-run.** Apply with `--apply` after review.

## Prerequisites

- [ ] Issue 05 complete — deploy verified
- [ ] Migration 25 (`add_below_threshold_settlement_status`) applied (confirmed in issue 05 check #5)
- [ ] `MINIMUM_TRANSFER_AMOUNT` env var present (defaults to `1.00`)

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Leave the PENDING entries alone | They'll trigger the stuck-payout Sentry alert (which is configured to fire after `STUCK_PAYOUT_THRESHOLD_HOURS=24`). Not blocking, just noise — but it's noise that masks real stuck-payout incidents. |
| Manual `UPDATE` SQL | Loses the script's safety check (`amount < MIN`). Scripted is auditable + idempotent. |
| Skip on prod, only run on staging | The staging entries we cleared were 5 sub-paise rows. Prod likely has its own backlog. |

## What to do

### 1. Dry-run

```bash
sudo docker exec ocpp-backend-prod python scripts/backfill_below_threshold.py 2>&1 | tee /tmp/below-threshold-dryrun.log
```

Read the output. Expected to show:
- Number of stuck PENDING entries with `payout < ₹1.00`
- Per-row info: id, franchisee_id, payout amount, age
- Total row count to be flipped

If the count is zero — there's nothing to do, the issue is `completed` immediately.

If the count is non-zero — review individual rows for sanity. Real sub-floor payouts have tiny amounts (paise-range); anything suspicious (e.g. payout = ₹50, why is this PENDING?) needs investigation before --apply.

### 2. Apply

```bash
sudo docker exec ocpp-backend-prod python scripts/backfill_below_threshold.py --apply 2>&1 | tee /tmp/below-threshold-apply.log
```

Expected output: confirmation of N rows flipped to BELOW_THRESHOLD.

### 3. Verify

```bash
DB_USER=$(grep ^DB_USER= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)

# Confirm no remaining PENDING sub-floor entries
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT COUNT(*) AS still_stuck
  FROM commission_ledger_entry
  WHERE settlement_status='PENDING' AND franchisee_payout < 1.00;
"
# Expected: 0

# Spot-check the new BELOW_THRESHOLD rows
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT id, franchisee_id, franchisee_payout, settlement_status
  FROM commission_ledger_entry
  WHERE settlement_status='BELOW_THRESHOLD'
  ORDER BY id DESC LIMIT 10;
"
```

## Definition of done

- Dry-run completed + output reviewed
- (If non-zero count) `--apply` completed cleanly
- Verification query returns 0 stuck-PENDING sub-floor entries
- (If non-zero count) Spot-check shows the flipped rows are in `BELOW_THRESHOLD`
- The stuck-payout Sentry alert should NOT fire on the next sweep for these entries
