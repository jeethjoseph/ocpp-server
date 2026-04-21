from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" ADD "funds_on_hold" BOOL NOT NULL DEFAULT False;
        ALTER TABLE "franchisee" ADD "transfers_enabled" BOOL NOT NULL DEFAULT True;
        ALTER TABLE "qr_payment" ADD "refund_failure_reason" TEXT;
        ALTER TABLE "qr_payment" ADD "refund_processed_at" TIMESTAMPTZ;
        CREATE INDEX IF NOT EXISTS "idx_qr_payment_razorpa_ad810d" ON "qr_payment" ("razorpay_refund_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_qr_payment_razorpa_ad810d";
        ALTER TABLE "qr_payment" DROP COLUMN "refund_failure_reason";
        ALTER TABLE "qr_payment" DROP COLUMN "refund_processed_at";
        ALTER TABLE "franchisee" DROP COLUMN "funds_on_hold";
        ALTER TABLE "franchisee" DROP COLUMN "transfers_enabled";"""
