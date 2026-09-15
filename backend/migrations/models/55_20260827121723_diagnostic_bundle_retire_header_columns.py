from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" DROP CONSTRAINT IF EXISTS "uid_diagnostic__charger_7db1f0";
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "bundle_seq" DROP NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "overflow_delta" DROP DEFAULT;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "overflow_delta" DROP NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "epoch" DROP DEFAULT;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "epoch" DROP NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "header_valid" DROP DEFAULT;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "header_valid" DROP NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "gap_records" DROP DEFAULT;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "gap_records" DROP NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "bundle_seq" SET NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "overflow_delta" SET NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "overflow_delta" SET DEFAULT 0;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "epoch" SET NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "epoch" SET DEFAULT 0;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "header_valid" SET NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "header_valid" SET DEFAULT True;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "gap_records" SET NOT NULL;
        ALTER TABLE "diagnostic_bundle" ALTER COLUMN "gap_records" SET DEFAULT 0;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_diagnostic__charger_7db1f0" ON "diagnostic_bundle" ("charger_id", "epoch", "bundle_seq");"""
