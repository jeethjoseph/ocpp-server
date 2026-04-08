from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" ADD "gst_amount" DECIMAL(10,2);
        ALTER TABLE "tariff" ADD "gst_percent" DECIMAL(5,2) NOT NULL DEFAULT 18;
        ALTER TABLE "transaction" ADD "total_billed" DECIMAL(10,2);
        ALTER TABLE "transaction" ADD "energy_charge" DECIMAL(10,2);
        ALTER TABLE "transaction" ADD "gst_amount" DECIMAL(10,2);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "tariff" DROP COLUMN "gst_percent";
        ALTER TABLE "qr_payment" DROP COLUMN "gst_amount";
        ALTER TABLE "transaction" DROP COLUMN "total_billed";
        ALTER TABLE "transaction" DROP COLUMN "energy_charge";
        ALTER TABLE "transaction" DROP COLUMN "gst_amount";"""
