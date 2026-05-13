#!/usr/bin/env python3
"""One-shot backfill: flip stuck PENDING ledger entries with sub-floor
payout to BELOW_THRESHOLD.

These entries were created before the BELOW_THRESHOLD state existed and
will never transfer because franchisee_payout < MINIMUM_TRANSFER_AMOUNT.
Leaving them as PENDING is misleading and makes the retry sweep skip
them silently.

Usage:
    docker exec ocpp-backend python scripts/backfill_below_threshold.py            # dry-run
    docker exec ocpp-backend python scripts/backfill_below_threshold.py --apply    # commit
"""

import argparse
import asyncio
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_below_threshold")

MIN_TRANSFER_AMOUNT = Decimal(os.getenv("MINIMUM_TRANSFER_AMOUNT", "1.00"))


async def run(apply: bool) -> int:
    from database import init_db, close_db
    from models import CommissionLedgerEntry, SettlementStatusEnum

    await init_db()
    try:
        candidates = await CommissionLedgerEntry.filter(
            settlement_status=SettlementStatusEnum.PENDING,
            franchisee_payout__lt=MIN_TRANSFER_AMOUNT,
        ).all()

        if not candidates:
            logger.info("No stuck PENDING entries below ₹%s — nothing to do.", MIN_TRANSFER_AMOUNT)
            return 0

        logger.info(
            "Found %d PENDING ledger entries with franchisee_payout < ₹%s:",
            len(candidates), MIN_TRANSFER_AMOUNT,
        )
        for e in candidates:
            logger.info(
                "  id=%-5d franchisee_id=%-3d payout=₹%s gross=₹%s razorpay_payment_id=%s",
                e.id, e.franchisee_id, e.franchisee_payout, e.gross_amount,
                e.razorpay_payment_id,
            )

        if not apply:
            logger.info("\nDry-run only. Re-run with --apply to commit.")
            return len(candidates)

        updated = await CommissionLedgerEntry.filter(
            settlement_status=SettlementStatusEnum.PENDING,
            franchisee_payout__lt=MIN_TRANSFER_AMOUNT,
        ).update(settlement_status=SettlementStatusEnum.BELOW_THRESHOLD)
        logger.info("\n✅ Flipped %d entries to BELOW_THRESHOLD.", updated)
        return updated
    finally:
        await close_db()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Commit the update. Without this flag the script is a dry-run.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(run(apply=args.apply)))


if __name__ == "__main__":
    main()
