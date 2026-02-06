from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger" ADD "external_charger_id" VARCHAR(255) UNIQUE;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_charger_externa_4c7f59" ON "charger" ("external_charger_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_charger_externa_4c7f59";
        ALTER TABLE "charger" DROP COLUMN "external_charger_id";"""
