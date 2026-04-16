from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "app_user" ALTER COLUMN "auth_provider" TYPE VARCHAR(20);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "app_user" ALTER COLUMN "auth_provider" TYPE VARCHAR(6);
    """
