from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "razorpay_api_log" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "method" VARCHAR(10) NOT NULL,
    "endpoint" VARCHAR(255) NOT NULL,
    "request_body" JSONB,
    "response_status" INT,
    "response_body" JSONB,
    "success" BOOL NOT NULL,
    "error_message" TEXT,
    "razorpay_account_id" VARCHAR(50),
    "franchisee_id" INT REFERENCES "franchisee" ("id") ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS "idx_razorpay_ap_created_0d67a9" ON "razorpay_api_log" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_razorpay_ap_razorpa_ba9c9c" ON "razorpay_api_log" ("razorpay_account_id");
CREATE INDEX IF NOT EXISTS "idx_razorpay_ap_franchi_d6a0fb" ON "razorpay_api_log" ("franchisee_id");
COMMENT ON TABLE "razorpay_api_log" IS 'Outbound audit trail for mutating Razorpay onboarding-chain calls.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "razorpay_api_log";"""
