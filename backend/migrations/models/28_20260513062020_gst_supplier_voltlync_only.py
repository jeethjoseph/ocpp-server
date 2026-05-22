from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- 1. Drop the old uniqueness constraints (both the regular FK-based
        --    unique and the partial NULL-aware indexes from migration 27).
        ALTER TABLE "gst_invoice_counter" DROP CONSTRAINT IF EXISTS "uid_gst_invoice_franchi_c0cd9c";
        ALTER TABLE "gst_invoice_counter" DROP CONSTRAINT IF EXISTS "uid_gst_invoice_franchi_88356d";
        ALTER TABLE "gst_invoice_counter" DROP CONSTRAINT IF EXISTS "fk_gst_invo_franchis_d4eeab2f";
        DROP INDEX IF EXISTS "uid_gst_invoice_counter_voltlync";
        DROP INDEX IF EXISTS "uid_gst_invoice_franchi_88356d";

        ALTER TABLE "gst_invoice" DROP CONSTRAINT IF EXISTS "uid_gst_invoice_franchi_1ad4c8";
        DROP INDEX IF EXISTS "uid_gst_invoice_franchi_1ad4c8";
        DROP INDEX IF EXISTS "uid_gst_invoice_voltlync_fy";

        -- 2. Normalize supplier identity on every existing row to VoltLync's
        --    canonical values. supplier_gstin intentionally left to the
        --    backfill script, which reads the real VOLTLYNC_GSTIN env var.
        UPDATE "gst_invoice" SET
            supplier_name = 'VOLTLYNC PRIVATE LIMITED',
            supplier_state = 'Kerala',
            supplier_state_code = '32';

        -- 3. Renumber every existing invoice gapless per (series, FY),
        --    dropping the now-meaningless F{franchisee_id} prefix segment.
        WITH ordered AS (
            SELECT id,
                'VL/' || series || '/' || REPLACE(financial_year, '-', '') || '/' ||
                LPAD(ROW_NUMBER() OVER (
                    PARTITION BY series, financial_year
                    ORDER BY invoice_date, id
                )::text, 5, '0') AS new_number
            FROM "gst_invoice"
        )
        UPDATE "gst_invoice" g
        SET invoice_number = o.new_number
        FROM ordered o
        WHERE g.id = o.id;

        -- 4. Drop the counter table's franchisee_id column and rebuild the
        --    counter rows from the renumbered invoices.
        ALTER TABLE "gst_invoice_counter" DROP COLUMN "franchisee_id";
        DELETE FROM "gst_invoice_counter";
        INSERT INTO "gst_invoice_counter" (series, financial_year, last_number)
        SELECT series, financial_year, COUNT(*)
        FROM "gst_invoice"
        GROUP BY series, financial_year;

        -- 5. Add the new uniqueness constraints.
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_series_178cbf"
            ON "gst_invoice" ("series", "financial_year", "invoice_number");
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_series_c8da19"
            ON "gst_invoice_counter" ("series", "financial_year");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Best-effort schema rollback. The renumbered invoice_number values
        -- and normalized supplier_* fields cannot be restored because the
        -- pre-migration values were not preserved.
        DROP INDEX IF EXISTS "uid_gst_invoice_series_c8da19";
        DROP INDEX IF EXISTS "uid_gst_invoice_series_178cbf";
        ALTER TABLE "gst_invoice_counter" ADD "franchisee_id" INT;
        ALTER TABLE "gst_invoice_counter" ADD CONSTRAINT "fk_gst_invo_franchis_d4eeab2f"
            FOREIGN KEY ("franchisee_id") REFERENCES "franchisee" ("id") ON DELETE CASCADE;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_franchi_c0cd9c"
            ON "gst_invoice_counter" ("franchisee_id", "series", "financial_year");
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_franchi_1ad4c8"
            ON "gst_invoice" ("franchisee_id", "financial_year", "invoice_number")
            WHERE "franchisee_id" IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_voltlync_fy"
            ON "gst_invoice" ("financial_year", "invoice_number")
            WHERE "franchisee_id" IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_counter_voltlync"
            ON "gst_invoice_counter" ("series", "financial_year")
            WHERE "franchisee_id" IS NULL;"""
