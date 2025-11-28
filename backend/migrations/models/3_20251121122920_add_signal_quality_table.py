from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "signal_quality" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "rssi" INT NOT NULL,
    "ber" INT NOT NULL,
    "timestamp" VARCHAR(50) NOT NULL,
    "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_signal_qual_created_9f0c6c" ON "signal_quality" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_signal_qual_charger_46e23a" ON "signal_quality" ("charger_id");
COMMENT ON TABLE "signal_quality" IS 'Stores cellular signal quality metrics from charge points.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "signal_quality";"""
