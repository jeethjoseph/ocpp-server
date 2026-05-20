from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "gst_invoice" ADD "tariff_per_kwh_all_in" DECIMAL(10,4);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "gst_invoice" DROP COLUMN "tariff_per_kwh_all_in";"""
