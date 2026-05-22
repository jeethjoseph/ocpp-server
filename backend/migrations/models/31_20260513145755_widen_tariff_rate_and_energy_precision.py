from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    # Deduplicated: Aerich emits each FloatField→DecimalField ALTER twice.
    # On large tables (meter_value), the second ALTER doubles rewrite time.
    return """
        ALTER TABLE "commission_ledger_entry" ALTER COLUMN "tariff_rate_per_kwh" TYPE DECIMAL(8,4) USING "tariff_rate_per_kwh"::DECIMAL(8,4);
        ALTER TABLE "commission_ledger_entry" ALTER COLUMN "energy_consumed_kwh" TYPE DECIMAL(12,3) USING "energy_consumed_kwh"::DECIMAL(12,3);
        ALTER TABLE "gst_invoice" ALTER COLUMN "energy_consumed_kwh" TYPE DECIMAL(12,3) USING "energy_consumed_kwh"::DECIMAL(12,3);
        ALTER TABLE "meter_value" ALTER COLUMN "reading_kwh" TYPE DECIMAL(12,3) USING "reading_kwh"::DECIMAL(12,3);
        ALTER TABLE "tariff" ALTER COLUMN "rate_per_kwh" TYPE DECIMAL(8,4) USING "rate_per_kwh"::DECIMAL(8,4);
        ALTER TABLE "transaction" ALTER COLUMN "start_meter_kwh" TYPE DECIMAL(12,3) USING "start_meter_kwh"::DECIMAL(12,3);
        ALTER TABLE "transaction" ALTER COLUMN "end_meter_kwh" TYPE DECIMAL(12,3) USING "end_meter_kwh"::DECIMAL(12,3);
        ALTER TABLE "transaction" ALTER COLUMN "energy_consumed_kwh" TYPE DECIMAL(12,3) USING "energy_consumed_kwh"::DECIMAL(12,3);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "tariff" ALTER COLUMN "rate_per_kwh" TYPE DECIMAL(5,2) USING "rate_per_kwh"::DECIMAL(5,2);
        ALTER TABLE "gst_invoice" ALTER COLUMN "energy_consumed_kwh" TYPE DOUBLE PRECISION USING "energy_consumed_kwh"::DOUBLE PRECISION;
        ALTER TABLE "meter_value" ALTER COLUMN "reading_kwh" TYPE DOUBLE PRECISION USING "reading_kwh"::DOUBLE PRECISION;
        ALTER TABLE "transaction" ALTER COLUMN "start_meter_kwh" TYPE DOUBLE PRECISION USING "start_meter_kwh"::DOUBLE PRECISION;
        ALTER TABLE "transaction" ALTER COLUMN "end_meter_kwh" TYPE DOUBLE PRECISION USING "end_meter_kwh"::DOUBLE PRECISION;
        ALTER TABLE "transaction" ALTER COLUMN "energy_consumed_kwh" TYPE DOUBLE PRECISION USING "energy_consumed_kwh"::DOUBLE PRECISION;
        ALTER TABLE "commission_ledger_entry" ALTER COLUMN "tariff_rate_per_kwh" TYPE DECIMAL(5,2) USING "tariff_rate_per_kwh"::DECIMAL(5,2);
        ALTER TABLE "commission_ledger_entry" ALTER COLUMN "energy_consumed_kwh" TYPE DOUBLE PRECISION USING "energy_consumed_kwh"::DOUBLE PRECISION;"""
