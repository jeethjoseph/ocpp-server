from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger_qr_code" DROP CONSTRAINT IF EXISTS "charger_qr_code_charger_id_key";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger_qr_code" ADD CONSTRAINT "charger_qr_code_charger_id_key" UNIQUE ("charger_id");"""
