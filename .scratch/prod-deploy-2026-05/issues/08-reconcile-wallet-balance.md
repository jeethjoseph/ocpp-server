Status: ready-for-agent

# Run `reconcile_wallet_balance.py` as validation (read-only)

## What to build

Read-only sanity check that the event-sourced wallet ledger (post migration 33) sums correctly. The script compares the derived balance (`SUM(amount) per wallet_id, signed by type`) against… well, against itself in different ways — looking for inconsistencies like negative derived balances, orphaned transactions, mismatched type+sign combinations.

This is **not** a backfill — migration 33 already normalized CHARGE_DEDUCT amounts. This is the validation that "the normalization worked + the wallet model is self-consistent now."

## Prerequisites

- [ ] Issue 05 complete (migration 33 applied)
- [ ] Issue 05 check #8 passed (no negative CHARGE_DEDUCT rows)

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Skip — trust that migration 33's `RAISE NOTICE` counts looked right | The notices show "this many rows changed" but don't prove "the resulting ledger sums to a non-negative balance per wallet." Different check. |
| Write the validation as a one-off SQL query | The script exists, does the job, and emits structured output. Use it. |
| Apply automatic fixes if drift found | The script is read-only by design. Any drift found is investigated case-by-case. Auto-fixing wallet balances is the kind of thing that loses customer money. |

## What to do

```bash
# Single SSM-friendly command:
sudo docker exec ocpp-backend-prod python scripts/reconcile_wallet_balance.py 2>&1 | tail -50
```

What the script outputs:
- Per-wallet summary: wallet_id, current derived balance, TOP_UP sum, CHARGE_DEDUCT sum
- Any wallets with negative derived balance (should be 0 wallets in steady state)
- Any wallets with TOP_UP rows but no `payment_metadata.status = 'COMPLETED'` (PENDING rows that haven't credited yet — normal during the Razorpay confirmation window)
- A summary line: total wallets checked, total flagged for review

## Expected outcomes

| Outcome | Meaning | Action |
|---|---|---|
| Zero anomalies, all wallets non-negative | Steady state ✅ | Done |
| A few wallets with PENDING top-ups in flight | Normal — those payments haven't confirmed yet | Note for follow-up; recheck in 1 hour |
| A few wallets with negative derived balance | Could be legit if a budget-cap dispatch failed (charger over-delivered energy). See CLAUDE.md wallet ledger section: "negative derived balance is observable, not impossible." | Investigate per-wallet. If small (under ~₹10), likely the normal "budget cap fail-safe" case. If large, real bug. |
| Many wallets flagged | Migration 33 didn't normalize correctly | STOP — major issue. Compare against pre-deploy `pg_dump`. |

## Verification

The script's exit code is `0` if everything looks healthy. If it exits non-zero, the output should explain why.

```bash
sudo docker exec ocpp-backend-prod python scripts/reconcile_wallet_balance.py
echo "Exit code: $?"
```

Optionally, sample-check the per-wallet sum manually:

```bash
DB_USER=$(grep ^DB_USER= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)
DB_NAME=$(grep ^DB_NAME= /home/ec2-user/ocpp-server/.env.prod | cut -d= -f2-)

# Pick a wallet with recent activity:
sudo docker exec ocpp-postgres-prod psql -U "$DB_USER" -d "$DB_NAME" -x -c "
  SELECT wallet_id,
         SUM(CASE WHEN type='TOP_UP'
                   AND (payment_metadata->>'status') = 'COMPLETED'
                  THEN amount ELSE 0 END)
         - SUM(CASE WHEN type='CHARGE_DEDUCT' THEN amount ELSE 0 END) AS derived_balance,
         COUNT(*) AS total_rows
  FROM wallet_transaction
  WHERE wallet_id IN (SELECT wallet_id FROM wallet_transaction ORDER BY created_at DESC LIMIT 5)
  GROUP BY wallet_id;
"
```

## Definition of done

- Script ran to completion
- Exit code is 0 OR any non-zero exit's output has been reviewed and the flagged wallets explained (e.g. PENDING top-ups still in flight)
- No "many wallets flagged" outcome (which would indicate migration 33 didn't normalize)
- Output saved to a file (e.g. `/tmp/wallet-reconcile-2026-05-27.log`) for retrospective
