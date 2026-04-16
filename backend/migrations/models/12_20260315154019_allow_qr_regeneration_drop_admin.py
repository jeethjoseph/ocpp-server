from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_charger_qr__charger_bc6f6e";
        ALTER TABLE "charger_qr_code" DROP CONSTRAINT IF EXISTS "fk_charger__charger_a0cacc31";
        DROP TABLE IF EXISTS "admin_user";
        ALTER TABLE "charger_qr_code" ADD CONSTRAINT "fk_charger__charger_a0cacc31" FOREIGN KEY ("charger_id") REFERENCES "charger" ("id") ON DELETE CASCADE;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger_qr_code" DROP CONSTRAINT IF EXISTS "fk_charger__charger_a0cacc31";
        ALTER TABLE "charger_qr_code" ADD CONSTRAINT "fk_charger__charger_a0cacc31" FOREIGN KEY ("charger_id") REFERENCES "charger" ("id") ON DELETE CASCADE;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_charger_qr__charger_bc6f6e" ON "charger_qr_code" ("charger_id");"""
