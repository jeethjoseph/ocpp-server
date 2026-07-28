from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "connector" ALTER COLUMN "connector_type" TYPE VARCHAR(255) USING "connector_type"::VARCHAR(255);
        COMMENT ON COLUMN "connector"."connector_type" IS 'TYPE2: Type2
TYPE1: Type1
SOCKET: Socket
CCS: CCS
CHADEMO: CHAdeMO
GBT: GB/T
DOMESTIC: domestic';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "connector" ALTER COLUMN "connector_type" TYPE VARCHAR(255) USING "connector_type"::VARCHAR(255);
        COMMENT ON COLUMN "connector"."connector_type" IS NULL;"""
