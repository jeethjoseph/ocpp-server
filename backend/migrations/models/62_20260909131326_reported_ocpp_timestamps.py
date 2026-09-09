from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "meter_value" ADD "measured_at" TIMESTAMPTZ;
        ALTER TABLE "transaction" ADD "reported_start_time" TIMESTAMPTZ;
        ALTER TABLE "transaction" ADD "reported_end_time" TIMESTAMPTZ;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "meter_value" DROP COLUMN "measured_at";
        ALTER TABLE "transaction" DROP COLUMN "reported_start_time";
        ALTER TABLE "transaction" DROP COLUMN "reported_end_time";"""
