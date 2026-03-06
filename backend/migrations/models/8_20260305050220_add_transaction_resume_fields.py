from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "transaction" ADD "suspended_at" TIMESTAMPTZ;
        ALTER TABLE "transaction" ADD "resumed_at" TIMESTAMPTZ;
        ALTER TABLE "transaction" ADD "resume_count" INT NOT NULL DEFAULT 0;
        COMMENT ON COLUMN "transaction"."transaction_status" IS 'STARTED: STARTED
PENDING_START: PENDING_START
RUNNING: RUNNING
SUSPENDED: SUSPENDED
PENDING_STOP: PENDING_STOP
STOPPED: STOPPED
COMPLETED: COMPLETED
CANCELLED: CANCELLED
FAILED: FAILED
BILLING_FAILED: BILLING_FAILED';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "transaction" DROP COLUMN "suspended_at";
        ALTER TABLE "transaction" DROP COLUMN "resumed_at";
        ALTER TABLE "transaction" DROP COLUMN "resume_count";
        COMMENT ON COLUMN "transaction"."transaction_status" IS 'STARTED: STARTED
PENDING_START: PENDING_START
RUNNING: RUNNING
PENDING_STOP: PENDING_STOP
STOPPED: STOPPED
COMPLETED: COMPLETED
CANCELLED: CANCELLED
FAILED: FAILED
BILLING_FAILED: BILLING_FAILED';"""
