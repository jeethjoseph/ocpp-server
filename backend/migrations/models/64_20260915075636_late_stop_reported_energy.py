from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "transaction" ADD "reported_energy_kwh" DECIMAL(12,3);
        ALTER TABLE "transaction" ADD "reported_end_meter_kwh" DECIMAL(12,3);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "transaction" DROP COLUMN "reported_energy_kwh";
        ALTER TABLE "transaction" DROP COLUMN "reported_end_meter_kwh";"""
