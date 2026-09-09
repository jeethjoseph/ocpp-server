import os

from tortoise import BaseDBAsyncClient

from policy import CHARGER_CODE_FORMAT_PATTERN, charger_code_series_pattern

# Aerich generated the two ADD COLUMNs and the unique index; the CHECK
# constraints are spliced in below, following migration 50's pattern.
#
# The series CHECK is environment-specific and therefore built at run time from
# ENVIRONMENT rather than hardcoded — one migration file is shared by both
# registers, but production may only ever hold VOW#### and staging only
# VOWS####. That is what makes a cross-register collision impossible without
# coordination: neither database can physically store the other's codes, and an
# Asset Code lands on issued GST invoices where a collision is permanent.
#
# Both patterns come from backend/policy.py rather than being written out here,
# so the DB constraint and every Python-side validation cannot drift apart.
#
# `asset_code` is nullable here and stays nullable until the backfill migration
# flips it. Adding a NOT NULL column with no value would fail on any non-empty
# register; the two-step is what lets the backfill be reviewed on its own.
#
# Consequence worth knowing, and identical to migration 50's: if a staging unit
# is ever physically moved into the production fleet, production's CHECK must be
# altered as an explicit step. That is deliberate — it forces the move to be a
# reviewed decision rather than something that happens silently.


async def upgrade(db: BaseDBAsyncClient) -> str:
    series_pattern = charger_code_series_pattern(os.getenv("ENVIRONMENT", "development"))
    return f"""
        ALTER TABLE "charger" ADD "asset_code" VARCHAR(12) UNIQUE;
        ALTER TABLE "charger" ADD "purpose" VARCHAR(7) NOT NULL DEFAULT 'PUBLIC';
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_charger_asset_c_948ce8" ON "charger" ("asset_code");
        ALTER TABLE "charger" ADD CONSTRAINT "ck_charger_asset_code_format"
            CHECK ("asset_code" IS NULL OR "asset_code" ~ '{CHARGER_CODE_FORMAT_PATTERN}');
        ALTER TABLE "charger" ADD CONSTRAINT "ck_charger_asset_code_series"
            CHECK ("asset_code" IS NULL OR "asset_code" ~ '{series_pattern}');"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger" DROP CONSTRAINT IF EXISTS "ck_charger_asset_code_series";
        ALTER TABLE "charger" DROP CONSTRAINT IF EXISTS "ck_charger_asset_code_format";
        DROP INDEX IF EXISTS "uid_charger_asset_c_948ce8";
        ALTER TABLE "charger" DROP COLUMN "asset_code";
        ALTER TABLE "charger" DROP COLUMN "purpose";"""
