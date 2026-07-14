from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    # ADR 0026: the tariff now EXCLUDES the gateway. Rename the operator-typed
    # column (value unchanged — it stays the customer-facing displayed number)
    # and recompute the base rate_per_kwh WITHOUT the old synthetic 2% gateway
    # factor: base = rate_gst_included / (1 + gst_pct/100). The gst_invoice
    # snapshot column is renamed only; its historical rows keep their original
    # (gateway-inclusive) value — invoices are immutable and each PDF re-renders
    # from its own stored component fields.
    # Defense-in-depth: cap how long the ACCESS EXCLUSIVE lock from RENAME will
    # wait behind any stray transaction, so a rename can never pile up the lock
    # queue and stall live queries. Renames are catalog-only (no table rewrite)
    # and `tariff` is tiny, so 3s is ample. Scoped to this migration's txn.
    return """
        SET LOCAL lock_timeout = '3s';
        ALTER TABLE "gst_invoice" RENAME COLUMN "tariff_per_kwh_all_in" TO "rate_gst_included";
        ALTER TABLE "tariff" RENAME COLUMN "tariff_per_kwh_all_in" TO "rate_gst_included";
        UPDATE "tariff"
           SET "rate_per_kwh" = ROUND("rate_gst_included" / (1 + "gst_percent" / 100), 4);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # Restore the pre-ADR-0026 back-derivation that baked in the synthetic 2%
    # gateway: rate_per_kwh = rate_gst_included × 0.98 / 1.18 (generalised to the
    # row's gst_percent and the 2% fee constant).
    return """
        UPDATE "tariff"
           SET "rate_per_kwh" = ROUND("rate_gst_included" * 0.98 / (1 + "gst_percent" / 100), 4);
        ALTER TABLE "tariff" RENAME COLUMN "rate_gst_included" TO "tariff_per_kwh_all_in";
        ALTER TABLE "gst_invoice" RENAME COLUMN "rate_gst_included" TO "tariff_per_kwh_all_in";"""
