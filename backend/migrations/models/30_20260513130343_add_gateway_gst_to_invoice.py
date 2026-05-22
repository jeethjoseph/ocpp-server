from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "gst_invoice" ADD "gateway_gst" DECIMAL(10,2);

        -- Inline backfill from the linked qr_payment row. Going forward,
        -- generate_invoice snapshots qr_payment.razorpay_gst onto this
        -- column at issue time. For existing rows we sweep here so the
        -- column is populated on day one without a separate script.
        UPDATE "gst_invoice" g
        SET gateway_gst = q.razorpay_gst
        FROM "qr_payment" q
        WHERE q.transaction_id = g.transaction_id
          AND q.razorpay_gst IS NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "gst_invoice" DROP COLUMN "gateway_gst";"""
