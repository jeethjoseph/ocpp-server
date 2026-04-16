from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "wallet_transaction" ADD "razorpay_order_id" VARCHAR(64);
        UPDATE "wallet_transaction"
           SET "razorpay_order_id" = payment_metadata->>'razorpay_order_id'
         WHERE payment_metadata ? 'razorpay_order_id';
        CREATE INDEX IF NOT EXISTS "idx_wallet_txn_order_id" ON "wallet_transaction" ("razorpay_order_id");
        CREATE INDEX IF NOT EXISTS "idx_qr_payment_customer_vpa" ON "qr_payment" ("customer_vpa");
        CREATE INDEX IF NOT EXISTS "idx_qr_payment_charger_status_txn" ON "qr_payment" ("charger_id", "status", "transaction_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_qr_payment_charger_status_txn";
        DROP INDEX IF EXISTS "idx_qr_payment_customer_vpa";
        DROP INDEX IF EXISTS "idx_wallet_txn_order_id";
        ALTER TABLE "wallet_transaction" DROP COLUMN "razorpay_order_id";"""
