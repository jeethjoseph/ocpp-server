from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- 1. Drop the unique constraints from migration 28 (single-counter model).
        ALTER TABLE "gst_invoice_counter" DROP CONSTRAINT IF EXISTS "uid_gst_invoice_series_c8da19";
        DROP INDEX IF EXISTS "uid_gst_invoice_series_c8da19";
        ALTER TABLE "gst_invoice" DROP CONSTRAINT IF EXISTS "uid_gst_invoice_series_178cbf";
        DROP INDEX IF EXISTS "uid_gst_invoice_series_178cbf";

        -- 2. Add new columns.
        ALTER TABLE "gst_invoice" ADD "refund_amount" DECIMAL(10,2);
        ALTER TABLE "gst_invoice" ADD "franchisee_business_name" VARCHAR(255);
        ALTER TABLE "gst_invoice" ADD "franchisee_gstin" VARCHAR(20);
        ALTER TABLE "gst_invoice" ADD "franchisee_address" TEXT;
        ALTER TABLE "gst_invoice" ADD "franchisee_state" VARCHAR(100);
        ALTER TABLE "gst_invoice" ADD "franchisee_state_code" VARCHAR(5);
        ALTER TABLE "gst_invoice_counter" ADD "franchisee_id" INT
            REFERENCES "franchisee" ("id") ON DELETE CASCADE;

        -- 3. Renumber every existing invoice per (franchisee, series, FY).
        --    Rows with NULL franchisee stay numbered VL/{SERIES}/{FY}/{SEQ:05d};
        --    rows with a franchisee become VL/F{id}/{SERIES}/{FY}/{SEQ:05d}.
        WITH ordered AS (
            SELECT id,
                CASE
                    WHEN franchisee_id IS NULL THEN
                        'VL/' || series || '/' || REPLACE(financial_year, '-', '') || '/' ||
                        LPAD(ROW_NUMBER() OVER (
                            PARTITION BY series, financial_year
                            ORDER BY invoice_date, id
                        )::text, 5, '0')
                    ELSE
                        'VL/F' || franchisee_id || '/' || series || '/' ||
                        REPLACE(financial_year, '-', '') || '/' ||
                        LPAD(ROW_NUMBER() OVER (
                            PARTITION BY franchisee_id, series, financial_year
                            ORDER BY invoice_date, id
                        )::text, 5, '0')
                END AS new_number
            FROM "gst_invoice"
        )
        UPDATE "gst_invoice" g SET invoice_number = o.new_number
        FROM ordered o WHERE g.id = o.id;

        -- 4. Backfill franchisee snapshot columns from the live franchisee table.
        UPDATE "gst_invoice" g
        SET franchisee_business_name = f.business_name,
            franchisee_gstin         = f.gstin,
            franchisee_address       = f.address,
            franchisee_state         = f.state,
            franchisee_state_code    = f.state_code
        FROM "franchisee" f
        WHERE g.franchisee_id = f.id;

        -- 5. Restore the gross/refund split for QR sessions. Migration 27 had
        --    baked refund into transaction_amount; we now want them separate.
        UPDATE "gst_invoice" g
        SET refund_amount      = COALESCE(q.refund_amount, 0),
            transaction_amount = q.amount_paid
        FROM "qr_payment" q
        WHERE q.transaction_id = g.transaction_id;

        -- 6. Rebuild the counter table from the renumbered invoices.
        DELETE FROM "gst_invoice_counter";
        INSERT INTO "gst_invoice_counter" (franchisee_id, series, financial_year, last_number)
        SELECT franchisee_id, series, financial_year, COUNT(*)
        FROM "gst_invoice"
        GROUP BY franchisee_id, series, financial_year;

        -- 7. New uniqueness — partial indexes so the NULL-franchisee case
        --    (VoltLync-owned) is properly covered. Postgres treats NULL as
        --    distinct in a regular UNIQUE index.
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_franchi_db527f"
            ON "gst_invoice" ("franchisee_id", "series", "financial_year", "invoice_number")
            WHERE "franchisee_id" IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_voltlync_db527f"
            ON "gst_invoice" ("series", "financial_year", "invoice_number")
            WHERE "franchisee_id" IS NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_franchi_88356d"
            ON "gst_invoice_counter" ("franchisee_id", "series", "financial_year")
            WHERE "franchisee_id" IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_counter_voltlync"
            ON "gst_invoice_counter" ("series", "financial_year")
            WHERE "franchisee_id" IS NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Best-effort: renumbered invoice_number, snapshot fields, and the
        -- gross/refund split are not reconstructible from the current state.
        DROP INDEX IF EXISTS "uid_gst_invoice_counter_voltlync";
        DROP INDEX IF EXISTS "uid_gst_invoice_franchi_88356d";
        DROP INDEX IF EXISTS "uid_gst_invoice_voltlync_db527f";
        DROP INDEX IF EXISTS "uid_gst_invoice_franchi_db527f";
        ALTER TABLE "gst_invoice_counter" DROP COLUMN IF EXISTS "franchisee_id";
        ALTER TABLE "gst_invoice" DROP COLUMN IF EXISTS "franchisee_state_code";
        ALTER TABLE "gst_invoice" DROP COLUMN IF EXISTS "franchisee_state";
        ALTER TABLE "gst_invoice" DROP COLUMN IF EXISTS "franchisee_address";
        ALTER TABLE "gst_invoice" DROP COLUMN IF EXISTS "franchisee_gstin";
        ALTER TABLE "gst_invoice" DROP COLUMN IF EXISTS "franchisee_business_name";
        ALTER TABLE "gst_invoice" DROP COLUMN IF EXISTS "refund_amount";
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_series_178cbf"
            ON "gst_invoice" ("series", "financial_year", "invoice_number");
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_gst_invoice_series_c8da19"
            ON "gst_invoice_counter" ("series", "financial_year");"""
