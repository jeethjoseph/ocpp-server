from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger" ADD "availability" VARCHAR(11) NOT NULL DEFAULT 'Operative';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger" DROP COLUMN "availability";"""
