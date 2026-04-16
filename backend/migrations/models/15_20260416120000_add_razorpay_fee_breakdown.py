from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" ADD "razorpay_commission" DECIMAL(10,2);
        ALTER TABLE "qr_payment" ADD "razorpay_gst" DECIMAL(10,2);
        ALTER TABLE "qr_payment" ADD "fee_source" VARCHAR(20);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" DROP COLUMN "razorpay_commission";
        ALTER TABLE "qr_payment" DROP COLUMN "razorpay_gst";
        ALTER TABLE "qr_payment" DROP COLUMN "fee_source";"""
