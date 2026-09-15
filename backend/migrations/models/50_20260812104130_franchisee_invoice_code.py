import os

from tortoise import BaseDBAsyncClient

from policy import franchisee_code_backfill_offset, franchisee_code_block

# Aerich generated the ADD COLUMN and unique index; the CHECK constraints and
# the backfill are spliced in below.
#
# The block CHECK is environment-specific and therefore built at run time from
# ENVIRONMENT rather than hardcoded — one migration file is shared by both
# registers, but production may only ever hold F0001-F8999 and staging only
# F9000-F9999. That is what makes a cross-register collision impossible without
# coordination: neither database can physically store the other's codes.
#
# Consequence worth knowing: if staging's franchisees are ever migrated into
# production, production's CHECK must be altered as an explicit step of that
# migration. That is deliberate — it forces the merge to be a reviewed decision
# rather than something that happens silently, which is how the original
# duplicate invoice numbers arose.


async def upgrade(db: BaseDBAsyncClient) -> str:
    environment = os.getenv("ENVIRONMENT", "development")
    low, high = franchisee_code_block(environment)
    offset = franchisee_code_backfill_offset(environment)
    return f"""
        ALTER TABLE "franchisee" ADD "invoice_code" VARCHAR(5);
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_franchisee_invoice_fcb277" ON "franchisee" ("invoice_code");
        ALTER TABLE "franchisee" ADD CONSTRAINT "ck_franchisee_invoice_code_format"
            CHECK ("invoice_code" IS NULL OR "invoice_code" ~ '^F[0-9]{{4}}$');
        ALTER TABLE "franchisee" ADD CONSTRAINT "ck_franchisee_invoice_code_block"
            CHECK (
                "invoice_code" IS NULL
                OR CAST(substring("invoice_code" FROM 2) AS INTEGER) BETWEEN {low} AND {high}
            );
        UPDATE "franchisee"
           SET "invoice_code" = 'F' || lpad(CAST({offset} + "id" AS TEXT), 4, '0')
         WHERE "invoice_code" IS NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "franchisee" DROP CONSTRAINT IF EXISTS "ck_franchisee_invoice_code_block";
        ALTER TABLE "franchisee" DROP CONSTRAINT IF EXISTS "ck_franchisee_invoice_code_format";
        DROP INDEX IF EXISTS "uid_franchisee_invoice_fcb277";
        ALTER TABLE "franchisee" DROP COLUMN "invoice_code";"""
