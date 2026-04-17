from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "franchisee" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "business_name" VARCHAR(255) NOT NULL,
    "business_type" VARCHAR(15),
    "contact_name" VARCHAR(255) NOT NULL,
    "contact_email" VARCHAR(255) NOT NULL UNIQUE,
    "contact_phone" VARCHAR(20) NOT NULL,
    "address" TEXT,
    "pan_number" VARCHAR(10) UNIQUE,
    "gstin" VARCHAR(15) UNIQUE,
    "tan_number" VARCHAR(10),
    "state" VARCHAR(100),
    "state_code" VARCHAR(5),
    "bank_account_name" VARCHAR(255),
    "bank_account_number" VARCHAR(30),
    "bank_ifsc_code" VARCHAR(11),
    "razorpay_account_id" VARCHAR(50) UNIQUE,
    "razorpay_account_status" VARCHAR(50),
    "razorpay_onboarding_url" VARCHAR(500),
    "kyc_submitted_at" TIMESTAMPTZ,
    "kyc_verified_at" TIMESTAMPTZ,
    "commission_percent" DECIMAL(5,2) NOT NULL DEFAULT 20,
    "commission_effective_from" DATE NOT NULL,
    "tds_rate_percent" DECIMAL(5,2) NOT NULL DEFAULT 10,
    "tds_pan_verified" BOOL NOT NULL DEFAULT False,
    "status" VARCHAR(23) NOT NULL DEFAULT 'DRAFT',
    "status_reason" TEXT,
    "activated_at" TIMESTAMPTZ,
    "deactivated_at" TIMESTAMPTZ,
    "notes" TEXT,
    "onboarded_by_id" INT REFERENCES "app_user" ("id") ON DELETE CASCADE,
    "user_id" INT UNIQUE REFERENCES "app_user" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "franchisee"."business_type" IS 'INDIVIDUAL: INDIVIDUAL\nPROPRIETORSHIP: PROPRIETORSHIP\nPARTNERSHIP: PARTNERSHIP\nPRIVATE_LIMITED: PRIVATE_LIMITED\nLLP: LLP';
COMMENT ON COLUMN "franchisee"."status" IS 'DRAFT: DRAFT\nKYC_SUBMITTED: KYC_SUBMITTED\nKYC_UNDER_REVIEW: KYC_UNDER_REVIEW\nKYC_NEEDS_CLARIFICATION: KYC_NEEDS_CLARIFICATION\nACTIVE: ACTIVE\nSUSPENDED: SUSPENDED\nDEACTIVATED: DEACTIVATED';
        CREATE TABLE IF NOT EXISTS "commission_audit_log" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "previous_percent" DECIMAL(5,2),
    "new_percent" DECIMAL(5,2) NOT NULL,
    "reason" VARCHAR(22) NOT NULL,
    "effective_from" DATE NOT NULL,
    "notes" TEXT,
    "changed_by_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE CASCADE,
    "franchisee_id" INT NOT NULL REFERENCES "franchisee" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "commission_audit_log"."reason" IS 'INITIAL_SETUP: INITIAL_SETUP\nCONTRACT_RENEWAL: CONTRACT_RENEWAL\nPERFORMANCE_ADJUSTMENT: PERFORMANCE_ADJUSTMENT\nPROMOTION: PROMOTION\nADMIN_OVERRIDE: ADMIN_OVERRIDE';
        CREATE TABLE IF NOT EXISTS "commission_ledger_entry" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "gross_amount" DECIMAL(10,2) NOT NULL,
    "payment_method" VARCHAR(20) NOT NULL,
    "razorpay_payment_id" VARCHAR(255),
    "refund_amount" DECIMAL(10,2) NOT NULL DEFAULT 0,
    "pg_fee_amount" DECIMAL(10,2) NOT NULL DEFAULT 0,
    "net_amount" DECIMAL(10,2) NOT NULL,
    "gst_collected" DECIMAL(10,2) NOT NULL,
    "net_excl_gst" DECIMAL(10,2) NOT NULL,
    "commission_percent" DECIMAL(5,2) NOT NULL,
    "platform_commission" DECIMAL(10,2) NOT NULL,
    "tds_rate_percent" DECIMAL(5,2) NOT NULL DEFAULT 0,
    "tds_amount" DECIMAL(10,2) NOT NULL DEFAULT 0,
    "transfer_fee" DECIMAL(10,2) NOT NULL DEFAULT 0,
    "franchisee_payout" DECIMAL(10,2) NOT NULL,
    "energy_consumed_kwh" DOUBLE PRECISION NOT NULL,
    "tariff_rate_per_kwh" DECIMAL(5,2) NOT NULL,
    "settlement_status" VARCHAR(18) NOT NULL DEFAULT 'PENDING',
    "razorpay_transfer_id" VARCHAR(255) UNIQUE,
    "transfer_initiated_at" TIMESTAMPTZ,
    "transfer_processed_at" TIMESTAMPTZ,
    "settled_at" TIMESTAMPTZ,
    "failure_reason" TEXT,
    "retry_count" INT NOT NULL DEFAULT 0,
    "idempotency_key" VARCHAR(255) NOT NULL UNIQUE,
    "franchisee_id" INT NOT NULL REFERENCES "franchisee" ("id") ON DELETE CASCADE,
    "qr_payment_id" INT REFERENCES "qr_payment" ("id") ON DELETE CASCADE,
    "wallet_transaction_id" INT REFERENCES "wallet_transaction" ("id") ON DELETE CASCADE,
    "transaction_id" INT NOT NULL UNIQUE REFERENCES "transaction" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "commission_ledger_entry"."settlement_status" IS 'PENDING: PENDING\nTRANSFER_INITIATED: TRANSFER_INITIATED\nTRANSFER_PROCESSED: TRANSFER_PROCESSED\nSETTLED: SETTLED\nFAILED: FAILED\nREVERSED: REVERSED\nON_HOLD: ON_HOLD';
        ALTER TABLE "tariff" ADD "hsn_sac_code" VARCHAR(10);
        ALTER TABLE "app_user" ALTER COLUMN "role" TYPE VARCHAR(10) USING "role"::VARCHAR(10);
        COMMENT ON COLUMN "app_user"."role" IS 'ADMIN: ADMIN
USER: USER
FRANCHISEE: FRANCHISEE';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        COMMENT ON COLUMN "app_user"."role" IS 'ADMIN: ADMIN
USER: USER';
        ALTER TABLE "app_user" ALTER COLUMN "role" TYPE VARCHAR(5) USING "role"::VARCHAR(5);
        ALTER TABLE "tariff" DROP COLUMN "hsn_sac_code";
        DROP TABLE IF EXISTS "commission_audit_log";
        DROP TABLE IF EXISTS "franchisee";
        DROP TABLE IF EXISTS "commission_ledger_entry";"""
