from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" ADD "razorpay_refund_speed_processed" VARCHAR(20);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" DROP COLUMN "razorpay_refund_speed_processed";"""
