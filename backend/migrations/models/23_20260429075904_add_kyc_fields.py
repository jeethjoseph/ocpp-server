from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" ADD "bank_account_type" VARCHAR(10);
        ALTER TABLE "franchisee" ADD "kyc_verifications" JSONB;
        ALTER TABLE "franchisee_stakeholder" ADD "residential_country" VARCHAR(2) NOT NULL DEFAULT 'IN';
        ALTER TABLE "franchisee_stakeholder" ADD "residential_city" VARCHAR(100);
        ALTER TABLE "franchisee_stakeholder" ADD "residential_state" VARCHAR(100);
        ALTER TABLE "franchisee_stakeholder" ADD "residential_postal_code" VARCHAR(10);
        ALTER TABLE "franchisee_stakeholder" ADD "residential_street" VARCHAR(255);
        UPDATE "franchisee" SET "bank_account_type" = 'savings' WHERE "bank_account_type" IS NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" DROP COLUMN "bank_account_type";
        ALTER TABLE "franchisee" DROP COLUMN "kyc_verifications";
        ALTER TABLE "franchisee_stakeholder" DROP COLUMN "residential_country";
        ALTER TABLE "franchisee_stakeholder" DROP COLUMN "residential_city";
        ALTER TABLE "franchisee_stakeholder" DROP COLUMN "residential_state";
        ALTER TABLE "franchisee_stakeholder" DROP COLUMN "residential_postal_code";
        ALTER TABLE "franchisee_stakeholder" DROP COLUMN "residential_street";"""
