from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" ADD "city" VARCHAR(100);
        ALTER TABLE "franchisee" ADD "pincode" VARCHAR(10);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" DROP COLUMN "pincode";
        ALTER TABLE "franchisee" DROP COLUMN "city";"""
