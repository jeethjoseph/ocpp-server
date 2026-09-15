import os

from tortoise import BaseDBAsyncClient

from policy import charger_code_series

# Allocate Asset Codes from a Postgres sequence (ADR 0028, slice 02 revised).
#
# WHY A SEQUENCE RATHER THAN max + 1. Reading the maximum and adding one is a
# read-modify-write, so two concurrent creates can read the same maximum and
# race for the same code. That race is survivable — the UNIQUE constraint
# catches it — but only via a retry loop wrapped around the whole create,
# because a UNIQUE violation aborts the entire Postgres transaction and every
# later statement in it. A sequence removes the race outright: `nextval` is
# atomic and never hands the same number to two callers, so there is nothing to
# retry and no retry loop to get wrong.
#
# GAPS ARE EXPECTED AND FINE. `nextval` does not roll back, so an insert that
# fails burns a number. ADR 0028 already commits to exactly this: codes are
# never reused and gaps are never backfilled, "including gaps that were never
# allocated — deliberately simpler than reuse what is provably free". A burned
# number is that same case arriving by a different route.
#
# The sequence starts after the highest code the backfill assigned, so it can
# never collide with a seeded stencil. Seeded from the data rather than a
# hardcoded number, because production and staging finish migration 59 at
# different maxima (VOW0015 and VOWS0010).
#
# The column DEFAULT is belt-and-braces for raw-SQL inserts (seed scripts,
# psql). It does NOT serve the ORM: Tortoise 0.25 has no `db_default` and
# always names every column in its INSERT, so an ORM write never falls through
# to a DEFAULT. The `allocate_asset_code` pre_save hook in models.py is what
# covers the ORM path.

SEQUENCE_NAME = "charger_asset_code_seq"


async def upgrade(db: BaseDBAsyncClient) -> str:
    series = charger_code_series(os.getenv("ENVIRONMENT", "development"))
    return f"""
        CREATE SEQUENCE IF NOT EXISTS "{SEQUENCE_NAME}";

        -- Start after the highest code already in this register. substring()
        -- strips the series letters; the CHECK from migration 58 guarantees
        -- every stored code is well-formed, so the cast is safe.
        SELECT setval(
            '{SEQUENCE_NAME}',
            COALESCE(
                (SELECT MAX(CAST(substring("asset_code" FROM '[0-9]+$') AS BIGINT))
                   FROM "charger"
                  WHERE "asset_code" LIKE '{series}%'),
                0
            ) + 1,
            false
        );

        ALTER TABLE "charger"
            ALTER COLUMN "asset_code"
            SET DEFAULT '{series}' || lpad(nextval('{SEQUENCE_NAME}')::TEXT, 4, '0');"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return f"""
        ALTER TABLE "charger" ALTER COLUMN "asset_code" DROP DEFAULT;
        DROP SEQUENCE IF EXISTS "{SEQUENCE_NAME}";"""
