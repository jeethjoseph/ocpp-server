from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "firmware_update" ADD "retry_count" INT NOT NULL DEFAULT 0;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_firmware_up_charger_b70c75" ON "firmware_update" ("charger_id", "firmware_file_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_firmware_up_charger_b70c75";
        ALTER TABLE "firmware_update" DROP COLUMN "retry_count";"""
