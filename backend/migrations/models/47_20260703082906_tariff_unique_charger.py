from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    # Dedup before adding the unique index: keep the earliest (lowest id) tariff
    # per charger, drop the rest. Duplicates arose from a non-atomic upsert race
    # with no constraint (see upsert-race-hardening issue 01). Observed dups are
    # byte-identical, so keeping min(id) loses no tariff value. Global tariffs
    # (charger_id IS NULL) are excluded — NULLs stay distinct under the index.
    return """
        DELETE FROM "tariff" a USING "tariff" b
        WHERE a."charger_id" = b."charger_id"
          AND a."charger_id" IS NOT NULL
          AND a."id" > b."id";
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_tariff_charger_081d1b" ON "tariff" ("charger_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_tariff_charger_081d1b";"""
