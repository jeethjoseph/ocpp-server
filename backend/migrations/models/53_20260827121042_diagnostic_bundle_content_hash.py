from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" ADD "content_sha256" VARCHAR(64);
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_diagnostic__charger_816911" ON "diagnostic_bundle" ("charger_id", "content_sha256");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_diagnostic__charger_816911";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "content_sha256";"""
