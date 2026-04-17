from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "gst_invoice" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "invoice_number" VARCHAR(50) NOT NULL UNIQUE,
    "status" VARCHAR(9) NOT NULL DEFAULT 'ISSUED',
    "invoice_date" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "supplier_name" VARCHAR(255) NOT NULL,
    "supplier_gstin" VARCHAR(20),
    "supplier_address" TEXT,
    "supplier_state" VARCHAR(100),
    "supplier_state_code" VARCHAR(5),
    "customer_name" VARCHAR(255),
    "customer_identifier" VARCHAR(255),
    "customer_address" TEXT,
    "station_name" VARCHAR(255),
    "station_location" VARCHAR(500),
    "charger_id_str" VARCHAR(255),
    "connector_type" VARCHAR(50),
    "energy_consumed_kwh" DOUBLE PRECISION NOT NULL,
    "tariff_rate_incl_tax" DECIMAL(10,2) NOT NULL,
    "charged_on" TIMESTAMPTZ,
    "duration_seconds" INT,
    "hsn_sac_code" VARCHAR(10) NOT NULL DEFAULT '998749',
    "energy_taxable_value" DECIMAL(10,2) NOT NULL,
    "gateway_charges" DECIMAL(10,2) NOT NULL DEFAULT 0,
    "gateway_hsn_code" VARCHAR(10) NOT NULL DEFAULT '997158',
    "total_taxable_value" DECIMAL(10,2) NOT NULL,
    "is_inter_state" BOOL NOT NULL DEFAULT False,
    "cgst_rate" DECIMAL(5,2),
    "cgst_amount" DECIMAL(10,2),
    "sgst_rate" DECIMAL(5,2),
    "sgst_amount" DECIMAL(10,2),
    "igst_rate" DECIMAL(5,2),
    "igst_amount" DECIMAL(10,2),
    "total_tax" DECIMAL(10,2) NOT NULL,
    "total_amount" DECIMAL(10,2) NOT NULL,
    "amount_in_words" VARCHAR(500),
    "payment_method" VARCHAR(20),
    "transaction_amount" DECIMAL(10,2),
    "refund_amount" DECIMAL(10,2),
    "pdf_url" VARCHAR(500),
    "cancelled_at" TIMESTAMPTZ,
    "cancellation_reason" TEXT,
    "franchisee_id" INT REFERENCES "franchisee" ("id") ON DELETE CASCADE,
    "user_id" INT REFERENCES "app_user" ("id") ON DELETE CASCADE,
    "transaction_id" INT NOT NULL UNIQUE REFERENCES "transaction" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "gst_invoice"."status" IS 'ISSUED: ISSUED\nCANCELLED: CANCELLED';
COMMENT ON TABLE "gst_invoice" IS 'Per-session customer-facing GST tax invoice.';
        CREATE TABLE IF NOT EXISTS "gst_invoice_counter" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "series" VARCHAR(10) NOT NULL,
    "financial_year" VARCHAR(10) NOT NULL,
    "last_number" INT NOT NULL DEFAULT 0,
    "franchisee_id" INT REFERENCES "franchisee" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_gst_invoice_franchi_88356d" UNIQUE ("franchisee_id", "series", "financial_year")
);
COMMENT ON TABLE "gst_invoice_counter" IS 'Sequential invoice numbering per (franchisee, series, FY).';
        CREATE TABLE IF NOT EXISTS "gst_credit_note" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "credit_note_number" VARCHAR(50) NOT NULL UNIQUE,
    "reason" VARCHAR(255) NOT NULL,
    "credit_amount" DECIMAL(10,2) NOT NULL,
    "cgst_amount" DECIMAL(10,2),
    "sgst_amount" DECIMAL(10,2),
    "igst_amount" DECIMAL(10,2),
    "issue_date" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "pdf_url" VARCHAR(500),
    "franchisee_id" INT REFERENCES "franchisee" ("id") ON DELETE CASCADE,
    "original_invoice_id" INT NOT NULL REFERENCES "gst_invoice" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "gst_credit_note" IS 'Credit note against a GST invoice (for refunds/corrections).';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "gst_invoice";
        DROP TABLE IF EXISTS "gst_invoice_counter";
        DROP TABLE IF EXISTS "gst_credit_note";"""
