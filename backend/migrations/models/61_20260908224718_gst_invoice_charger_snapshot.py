from tortoise import BaseDBAsyncClient

# GST Invoice charger snapshot (ADR 0028, slice 04).
#
# `charger_id_str` keeps holding exactly what was PRINTED: a
# charge_point_string_id UUID before the cutover, an Asset Code after it. The
# two eras stay separable by ^VOWS?[0-9]{4,}$. Two internal columns join it,
# never printed and never exported to the GST filings CSV.
#
# ISSUED INVOICES ARE NOT REWRITTEN. `charger_id_str` is backfilled only where
# `pdf_url IS NULL` — i.e. no PDF has been generated, so nothing a customer or
# an auditor has seen can change. This was ruled out in the 2026-07-31 charter
# and is not negotiable: a GST invoice is a frozen tax document.
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
