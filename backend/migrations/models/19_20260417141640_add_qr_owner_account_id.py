from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger_qr_code" ADD "owner_razorpay_account_id" VARCHAR(50);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger_qr_code" DROP COLUMN "owner_razorpay_account_id";"""
