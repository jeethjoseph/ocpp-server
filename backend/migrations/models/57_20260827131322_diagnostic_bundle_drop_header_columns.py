from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "header_valid";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "epoch";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "boot";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "bundle_seq";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "overflow_delta";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "last_record";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "overflow";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "gap_records";
        ALTER TABLE "diagnostic_bundle" DROP COLUMN "first_record";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "diagnostic_bundle" ADD "header_valid" BOOL;
        ALTER TABLE "diagnostic_bundle" ADD "epoch" INT;
        ALTER TABLE "diagnostic_bundle" ADD "boot" INT;
        ALTER TABLE "diagnostic_bundle" ADD "bundle_seq" INT;
        ALTER TABLE "diagnostic_bundle" ADD "overflow_delta" INT;
        ALTER TABLE "diagnostic_bundle" ADD "last_record" INT;
        ALTER TABLE "diagnostic_bundle" ADD "overflow" INT;
        ALTER TABLE "diagnostic_bundle" ADD "gap_records" INT;
        ALTER TABLE "diagnostic_bundle" ADD "first_record" INT;"""
