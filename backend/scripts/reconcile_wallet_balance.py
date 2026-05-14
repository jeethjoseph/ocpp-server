"""Reconciliation tool: stored wallet.balance (legacy) vs derived ledger SUM.

For every wallet, computes the balance derived from the wallet_transaction
log and compares it to the stored wallet.balance. Prints per-wallet drift,
exits non-zero if any drift exceeds the threshold (default Re 1).

Mixed-sign tolerance: pre-migration-32 CHARGE_DEDUCT rows store negative
amounts; post-migration-32 rows store positive. We normalise via ABS()
on the CHARGE_DEDUCT side so the script works against any mixed history.

Migration 33 (the ledger migration) auto-heals drift by writing adjustment
rows during the upgrade, so this script is informational. Operators should
sanity-check the report on staging and prod before applying the migration.
Unexpected drift may signal a deeper bug worth investigating before the
auto-heal silently absorbs it.

Usage:
  docker exec ocpp-backend python -m scripts.reconcile_wallet_balance [--threshold 1.00]
"""
import argparse
import asyncio
import sys
from decimal import Decimal

from tortoise import Tortoise

sys.path.insert(0, "/app")

from scripts._db import build_tortoise_config


# Raw SQL so the script doesn't depend on the Wallet model (which loses
# its `balance` attribute once the post-migration code is deployed). The
# derivation formula MUST stay aligned with the canonical version at
# `services/wallet_service.py:_BALANCE_SQL`. The only intentional
# difference: this script wraps CHARGE_DEDUCT in ABS() so it can run
# against pre-migration-33 databases where those rows still carry the
# legacy negative sign.
_DERIVATION_SQL = """
    SELECT w.id AS wallet_id,
           w.user_id,
           w.balance AS stored,
           COALESCE((
               SELECT SUM(CASE
                          WHEN type = 'TOP_UP'
                               AND payment_metadata->>'status' = 'COMPLETED'
                               THEN amount
                          WHEN type = 'CHARGE_DEDUCT'
                               THEN -ABS(amount)
                          ELSE 0
                      END)
                 FROM wallet_transaction
                WHERE wallet_id = w.id
           ), 0) AS derived
      FROM wallet w
"""


async def main(threshold: Decimal) -> int:
    await Tortoise.init(config=build_tortoise_config())
    try:
        conn = Tortoise.get_connection("default")
        _, rows = await conn.execute_query(_DERIVATION_SQL)
        drifts = []
        for row in rows:
            stored = Decimal(row["stored"] or 0).quantize(Decimal("0.01"))
            derived = Decimal(row["derived"]).quantize(Decimal("0.01"))
            drift = stored - derived
            if abs(drift) >= Decimal("0.01"):
                drifts.append((row["wallet_id"], row["user_id"], stored, derived, drift))
        wallets_count = len(rows)

        if not drifts:
            print(f"✅ {wallets_count} wallets, zero drift")
            return 0

        print(f"⚠️  {len(drifts)}/{wallets_count} wallets show drift:")
        print(f"  {'wallet_id':>10}  {'user_id':>10}  {'stored':>12}  {'derived':>12}  {'drift':>10}")
        for wid, uid, stored, derived, drift in drifts:
            print(f"  {wid:>10}  {uid:>10}  ₹{stored:>10}  ₹{derived:>10}  ₹{drift:>+9}")

        over_threshold = [d for d in drifts if abs(d[4]) > threshold]
        if over_threshold:
            print(
                f"\n❌ {len(over_threshold)} wallet(s) drift > ₹{threshold} threshold "
                "— investigate before applying the ledger migration."
            )
            return 1

        print(
            f"\nℹ️  All drifts within ₹{threshold} threshold; migration's "
            "auto-heal will absorb them as BALANCE_ADJUSTMENT rows."
        )
        return 0
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--threshold", type=Decimal, default=Decimal("1.00"),
        help="Drift amount in rupees above which the script exits non-zero (default 1.00)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.threshold)))
