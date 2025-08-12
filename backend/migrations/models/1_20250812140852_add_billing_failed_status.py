from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "transaction" ALTER COLUMN "transaction_status" TYPE VARCHAR(14) USING "transaction_status"::VARCHAR(14);
        COMMENT ON COLUMN "transaction"."transaction_status" IS 'STARTED: STARTED
PENDING_START: PENDING_START
RUNNING: RUNNING
PENDING_STOP: PENDING_STOP
STOPPED: STOPPED
COMPLETED: COMPLETED
CANCELLED: CANCELLED
FAILED: FAILED
BILLING_FAILED: BILLING_FAILED';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        COMMENT ON COLUMN "transaction"."transaction_status" IS 'STARTED: STARTED
PENDING_START: PENDING_START
RUNNING: RUNNING
PENDING_STOP: PENDING_STOP
STOPPED: STOPPED
COMPLETED: COMPLETED
CANCELLED: CANCELLED
FAILED: FAILED';
        ALTER TABLE "transaction" ALTER COLUMN "transaction_status" TYPE VARCHAR(13) USING "transaction_status"::VARCHAR(13);"""
