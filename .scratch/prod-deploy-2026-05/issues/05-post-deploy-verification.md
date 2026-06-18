Status: ready-for-agent

# Post-deploy verification — confirm migrations + backend health on prod

## What to build

Mechanical verification that the deploy from issue 04 actually achieved what it claimed. Not user-flow testing (that's issue 09) — this is "did the migrations apply, is the backend connecting to its DB, do the new feature flags read as expected."

If any check fails, STOP and investigate. Do not run backfills (issues 06-08) until everything here is green.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Skip mechanical checks, jump to feature smoke tests | Mechanical confirms "the deploy actually happened correctly." Feature tests can pass on partially-broken systems if the broken parts aren't exercised. |
| Just trust the `make prod-deploy` exit code | The Makefile doesn't gate on `aerich upgrade` success — entrypoint runs migrations and `exec`s uvicorn even if a non-fatal migration error happened. Need to verify explicitly. |

## What to do

This issue is `ready-for-agent` — the agent can drive these checks via SSM. Single SSM batch:

```bash
# All from a single SSM command for atomic snapshot:

echo "=== 1. Backend container status ==="
sudo docker ps --filter name=ocpp-backend-prod --format "table {{.Names}}\\t{{.Status}}"
# Expected: Up XX (healthy)

echo "=== 2. Backend env reflects new deploy ==="
sudo docker exec ocpp-backend-prod printenv DB_HOST DB_NAME DB_USER NEW_RELIC_APP_NAME SENTRY_ENVIRONMENT \
  VOLTLYNC_GSTIN AWS_S3_INVOICE_BUCKET AWS_S3_FIRMWARE_BUCKET
# Expected:
#   DB_HOST=postgres        ← still Docker postgres
#   DB_NAME=ocpp_prod_db
#   DB_USER=ocpp_prod
#   NEW_RELIC_APP_NAME=OCPP-Server-Production
#   SENTRY_ENVIRONMENT=production
#   VOLTLYNC_GSTIN=<non-empty>
#   AWS_S3_INVOICE_BUCKET=voltlync-invoices-prod
#   AWS_S3_FIRMWARE_BUCKET=voltlync-firmware-prod

echo "=== 3. Aerich head matches expected ==="
sudo docker exec ocpp-backend-prod aerich heads
# Expected exactly: 42_20260527070319_add_charger_availability.py

echo "=== 4. All migrations applied — count check ==="
DB_USER=$(grep ^DB_USER= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -tAc \
  "SELECT MAX(id), MAX(version) FROM aerich;"
# Expected: 42 (or whatever max id is) + the 42_... filename

echo "=== 5. Critical new columns exist ==="
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT column_name FROM information_schema.columns
  WHERE table_name='charger' AND column_name='availability';
"
# Expected: 1 row, availability
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT column_name FROM information_schema.columns
  WHERE table_name='gst_invoice'
  AND column_name IN ('place_of_supply_state_code', 'series', 'financial_year', 'gst_rate_percent');
"
# Expected: 4 rows

echo "=== 6. wallet.balance column dropped (migration 33) ==="
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT column_name FROM information_schema.columns
  WHERE table_name='wallet' AND column_name='balance';
"
# Expected: 0 rows — column has been removed

echo "=== 7. wallet_transaction CHECK constraint is VALID ==="
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT conname, convalidated FROM pg_constraint
  WHERE conname='wallet_transaction_amount_non_negative';
"
# Expected: 1 row, convalidated=t

echo "=== 8. No negative CHARGE_DEDUCT rows ==="
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -tAc "
  SELECT COUNT(*) FROM wallet_transaction WHERE type='CHARGE_DEDUCT' AND amount < 0;
"
# Expected: 0 — migration 33 should have normalized all of these

echo "=== 9. Recent startup logs ==="
sudo docker logs ocpp-backend-prod 2>&1 | grep -E "Migrations completed|Database initialized|New Relic APM: ENABLED|Sentry Error Tracking: ENABLED|Starting OCPP" | tail -10

echo "=== 10. Last 60s of error-level logs ==="
sudo docker logs ocpp-backend-prod --since 60s 2>&1 | grep -iE "fatal|cannot connect|password authentication|ssl error|exception" | head -10
# Expected: empty (or only benign init warnings)

echo "=== 11. Health endpoint ==="
curl -sf https://app.voltlync.com/health && echo " HEALTHY" || echo " UNHEALTHY"

echo "=== 12. Live OCPP traffic ==="
sudo docker logs ocpp-backend-prod --since 30s 2>&1 | grep -iE "Heartbeat|StatusNotification" | wc -l
# Expected: > 0 — chargers should be reconnecting + sending heartbeats
```

## Verification interpretation

| Check | Pass criteria | If fails |
|---|---|---|
| 1 | Container `healthy` after ~60s | Container restart-loop → check logs for migration error |
| 2 | All env vars non-empty + correct values | Re-do issue 02; restart backend |
| 3 | `aerich heads` shows migration 42 filename | Migration train didn't complete — check logs around the broken migration |
| 4 | Max aerich id ≥ 42 | Same as 3 |
| 5 | All listed columns exist | Migrations didn't apply — STOP, investigate, possibly roll back |
| 6 | 0 rows (column gone) | Migration 33 didn't apply — major problem |
| 7 | `convalidated = t` | Migration 33's redemption step failed — there are still negative CHARGE_DEDUCT amounts somewhere |
| 8 | 0 negative rows | Same — migration 33 normalization failed |
| 9 | All 5 log lines present | Backend startup incomplete — investigate |
| 10 | No matches | If there are matches, read them carefully — might be benign warnings or real problems |
| 11 | 200 HEALTHY | Backend not serving HTTP — check nginx and backend logs |
| 12 | > 0 in 30s | Chargers haven't reconnected yet (give it 60s) OR WebSocket layer is broken |

## Definition of done

- All 12 checks pass
- Verified by SSM output stored somewhere accessible (paste into the deploy thread)
- Aerich head matches `42_20260527070319_add_charger_availability.py`
- Wallet ledger structural changes (migration 33) verified — no negative CHARGE_DEDUCT rows, constraint VALID, balance column gone
- Issues 06, 07, 08 (backfills) can now proceed
