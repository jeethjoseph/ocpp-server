from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" ADD "refund_terminal_status" VARCHAR(20);
        ALTER TABLE "qr_payment" ALTER COLUMN "status" TYPE VARCHAR(18) USING "status"::VARCHAR(18);
        COMMENT ON COLUMN "qr_payment"."status" IS 'PAID: PAID
CHARGING: CHARGING
COMPLETED: COMPLETED
REFUNDED: REFUNDED
REFUND_FAILED: REFUND_FAILED
EXPIRED: EXPIRED
FAILED: FAILED
REFUND_IN_PROGRESS: REFUND_IN_PROGRESS';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "qr_payment" DROP COLUMN "refund_terminal_status";
        COMMENT ON COLUMN "qr_payment"."status" IS 'PAID: PAID
CHARGING: CHARGING
COMPLETED: COMPLETED
REFUNDED: REFUNDED
REFUND_FAILED: REFUND_FAILED
EXPIRED: EXPIRED
FAILED: FAILED';
        ALTER TABLE "qr_payment" ALTER COLUMN "status" TYPE VARCHAR(13) USING "status"::VARCHAR(13);"""
