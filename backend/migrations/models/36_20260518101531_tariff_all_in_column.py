from tortoise import BaseDBAsyncClient


# Module-level constant so the smoke test (`tests/test_tariff_all_in_migration.py`)
# can import the exact backfill SQL this migration ships with — no risk of test
# drifting from the migration. The `0.98` factor encodes the 2% gateway-fee
# assumption frozen at migration-write time; if RAZORPAY_PLATFORM_FEE_PERCENT
# is changed later, existing legacy-backfilled rows will violate the back-calc
# identity. The startup checker in `main.py` warns when that happens.
BACKFILL_UPDATE_SQL = """
    UPDATE "tariff"
       SET tariff_per_kwh_all_in = ROUND(rate_per_kwh * (1 + gst_percent / 100.0), 4),
           rate_per_kwh          = ROUND(rate_per_kwh * 0.98, 4)
"""


async def upgrade(db: BaseDBAsyncClient) -> str:
    return f"""
        -- ----------------------------------------------------------------------
        -- ADR 0003: introduce all-inclusive tariff column.
        --
        -- `tariff_per_kwh_all_in` is the operator-typed, customer-displayed
        -- per-kWh price. Includes GST and the synthetic 2% gateway fee.
        --
        -- Backfill strategy preserves today's customer-facing displayed number:
        --   • new all-in     = old rate_per_kwh × (1 + gst_percent/100)
        --   • new rate_per_kwh = old rate_per_kwh × 0.98
        --
        -- The shrink lets the back-derivation identity
        --   tariff_per_kwh_all_in × 0.98 / 1.18 = rate_per_kwh
        -- hold going forward. Franchisees absorb a 2% margin on legacy
        -- tariffs until they re-enter via the admin UI (manual coordination,
        -- not surfaced via a banner — see issue 04 history).
        --
        -- Three steps in one transaction:
        --   1. ADD COLUMN nullable so existing rows accept the alter.
        --   2. UPDATE backfill — both new column and the shrunk rate_per_kwh.
        --      (SQL shared with the smoke test via BACKFILL_UPDATE_SQL.)
        --   3. ALTER NOT NULL to lock the column.
        -- ----------------------------------------------------------------------

        -- 1. New column. all-in starts nullable for the backfill step.
        ALTER TABLE "tariff" ADD "tariff_per_kwh_all_in" DECIMAL(10,4);

        -- 2. Backfill. Quantize to 4dp so the stored values match the
        --    DecimalField precision exactly (no surprise rounding on first read).
        DO $$
        DECLARE migrated_count INT;
        BEGIN
            {BACKFILL_UPDATE_SQL.strip().rstrip(';')};
            GET DIAGNOSTICS migrated_count = ROW_COUNT;
            RAISE NOTICE 'Migration 36: backfilled tariff_per_kwh_all_in for % row(s); rate_per_kwh shrunk by 2%% (operator absorbs until re-entry)', migrated_count;
        END $$;

        -- 3. Lock the column. Every row now has a value.
        ALTER TABLE "tariff" ALTER COLUMN "tariff_per_kwh_all_in" SET NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Best-effort rollback. Practical recovery should be from a DB
        -- snapshot taken before the upgrade — running this downgrade
        -- restores the pre-migration rate_per_kwh values (un-shrinks the
        -- 2%) but cannot recover any operator edits made post-upgrade.
        UPDATE "tariff"
           SET rate_per_kwh = ROUND(rate_per_kwh / 0.98, 4);

        ALTER TABLE "tariff" DROP COLUMN "tariff_per_kwh_all_in";"""
