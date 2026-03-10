from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "app_user" ADD "upi_vpa" VARCHAR(255) UNIQUE;

        CREATE TABLE IF NOT EXISTS "charger_qr_code" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "razorpay_qr_code_id" VARCHAR(255) NOT NULL UNIQUE,
            "image_url" VARCHAR(500) NOT NULL,
            "short_url" VARCHAR(500),
            "is_active" BOOL NOT NULL DEFAULT TRUE,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "charger_id" INT NOT NULL UNIQUE REFERENCES "charger" ("id") ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS "idx_charger_qr_co_razorpa_5a1b2c" ON "charger_qr_code" ("razorpay_qr_code_id");

        CREATE TABLE IF NOT EXISTS "qr_payment" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "razorpay_payment_id" VARCHAR(255) NOT NULL UNIQUE,
            "razorpay_qr_code_id" VARCHAR(255) NOT NULL,
            "amount_paid" DECIMAL(10,2) NOT NULL,
            "customer_vpa" VARCHAR(255),
            "customer_name" VARCHAR(255),
            "customer_contact" VARCHAR(255),
            "energy_cost" DECIMAL(10,2),
            "platform_fee" DECIMAL(10,2),
            "refund_amount" DECIMAL(10,2),
            "razorpay_refund_id" VARCHAR(255),
            "status" VARCHAR(20) NOT NULL,
            "failure_reason" TEXT,
            "metadata" JSONB,
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE,
            "charger_qr_code_id" INT NOT NULL REFERENCES "charger_qr_code" ("id") ON DELETE CASCADE,
            "user_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL,
            "transaction_id" INT REFERENCES "transaction" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_qr_payment_razorpa_7d3e4f" ON "qr_payment" ("razorpay_payment_id");
        CREATE INDEX IF NOT EXISTS "idx_qr_payment_razorpa_8e4f5g" ON "qr_payment" ("razorpay_qr_code_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "qr_payment";
        DROP TABLE IF EXISTS "charger_qr_code";
        ALTER TABLE "app_user" DROP COLUMN IF EXISTS "upi_vpa";
    """
