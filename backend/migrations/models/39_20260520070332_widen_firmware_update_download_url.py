from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "firmware_update" ALTER COLUMN "download_url" TYPE TEXT USING "download_url"::TEXT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "firmware_update" ALTER COLUMN "download_url" TYPE VARCHAR(500) USING "download_url"::VARCHAR(500);"""
