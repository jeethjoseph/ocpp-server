from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" ADD "razorpay_product_id" VARCHAR(50);
        CREATE TABLE IF NOT EXISTS "franchisee_stakeholder" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "razorpay_stakeholder_id" VARCHAR(50) UNIQUE,
    "name" VARCHAR(255) NOT NULL,
    "email" VARCHAR(255) NOT NULL,
    "phone_primary" VARCHAR(20),
    "relationship_director" BOOL NOT NULL DEFAULT True,
    "relationship_executive" BOOL NOT NULL DEFAULT True,
    "pan_number" VARCHAR(10),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "franchisee_id" INT NOT NULL REFERENCES "franchisee" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "franchisee_stakeholder" IS 'Stakeholder (director / proprietor / beneficial owner) linked to a';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" DROP COLUMN "razorpay_product_id";
        DROP TABLE IF EXISTS "franchisee_stakeholder";"""
