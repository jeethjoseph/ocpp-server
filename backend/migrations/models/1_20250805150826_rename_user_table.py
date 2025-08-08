from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user" RENAME TO "app_user";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "app_user" RENAME TO "user";"""
