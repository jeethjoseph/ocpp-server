from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" ADD "first_utc" TIMESTAMPTZ;
        ALTER TABLE "diagnostic_bundle" ADD "ring_wrap_events" INT NOT NULL DEFAULT 0;
        ALTER TABLE "diagnostic_bundle" ADD "time_approximate" BOOL NOT NULL DEFAULT False;
        ALTER TABLE "diagnostic_bundle" ADD "last_utc" TIMESTAMPTZ;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "first_utc";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "ring_wrap_events";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "time_approximate";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "last_utc";"""
