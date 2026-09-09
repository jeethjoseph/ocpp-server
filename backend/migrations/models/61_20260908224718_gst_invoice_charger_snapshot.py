from tortoise import BaseDBAsyncClient

# GST Invoice charger snapshot (ADR 0028, slice 04).
#
# `charger_id_str` keeps holding exactly what was PRINTED: a
# charge_point_string_id UUID before the cutover, an Asset Code after it. The
# two eras stay separable by ^VOWS?[0-9]{4,}$. Two internal columns join it,
# never printed and never exported to the GST filings CSV.
#
# RENDERED INVOICES ARE NOT REWRITTEN. `charger_id_str` is backfilled only where
# `pdf_url IS NULL`.
#
# Be precise about what that gate means, because the obvious reading is wrong.
# PDFs are generated LAZILY, on first download (`routers/invoices.py`
# serve_invoice_pdf): the document is rendered from this row, uploaded to S3,
# and the key stored on `pdf_url`. So `pdf_url IS NULL` does NOT mean "not
# issued" — an invoice can be fully issued, numbered and declared, and still
# have a null `pdf_url` simply because nobody has clicked download. It means
# "no artifact has ever been produced from this row".
#
# That is exactly the right gate. Where an artifact exists it is an immutable
# S3 object that a customer has seen, so rewriting the column would make the
# database disagree with the document. Where none exists, nobody has ever seen
# the old value, and a future render legitimately shows the Asset Code.
#
# Measured 2026-09-09: production 445 invoices of which 6 rendered; staging
# 1193 of which 3. So nine invoices across both registers keep the UUID they
# printed, permanently, and the rest gain the Asset Code.
#
# The two NEW columns are backfilled for EVERY row, issued or not. They are
# internal by construction — never rendered on the PDF, never exported — so
# populating them alters no document. That is the point: `charger_ocpp_id` is
# what preserves the audit link from a post-cutover invoice back to the
# physical unit, and backfilling it historically means one uniform join for
# compliance queries spanning the cutover.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "gst_invoice" ADD "charger_station_id" INT;
        ALTER TABLE "gst_invoice" ADD "charger_ocpp_id" VARCHAR(255);

        -- Internal columns: every row, via the transaction -> charger join.
        UPDATE "gst_invoice" gi
           SET "charger_ocpp_id" = ch."charge_point_string_id",
               "charger_station_id" = ch."station_id"
          FROM "transaction" t
          JOIN "charger" ch ON ch."id" = t."charger_id"
         WHERE gi."transaction_id" = t."id"
           AND gi."charger_ocpp_id" IS NULL;

        -- Printed column: ONLY invoices with no PDF yet.
        UPDATE "gst_invoice" gi
           SET "charger_id_str" = ch."asset_code"
          FROM "transaction" t
          JOIN "charger" ch ON ch."id" = t."charger_id"
         WHERE gi."transaction_id" = t."id"
           AND gi."pdf_url" IS NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # charger_id_str is NOT restored to the UUID. Re-running the upgrade is
    # safe, and the pre-cutover value is still recoverable from the transaction
    # FK, so reversing it would trade a harmless no-op for a destructive guess.
    return """
        ALTER TABLE "gst_invoice" DROP COLUMN "charger_station_id";
        ALTER TABLE "gst_invoice" DROP COLUMN "charger_ocpp_id";"""
