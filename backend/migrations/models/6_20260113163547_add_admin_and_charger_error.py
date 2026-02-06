from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "charger_error" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "connector_id" INT NOT NULL,
    "status" VARCHAR(50) NOT NULL,
    "error_code" VARCHAR(50) NOT NULL,
    "vendor_error_code" VARCHAR(50),
    "vendor_id" VARCHAR(255),
    "info" VARCHAR(255),
    "error_timestamp" TIMESTAMPTZ,
    "is_resolved" BOOL NOT NULL DEFAULT False,
    "resolved_at" TIMESTAMPTZ,
    "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_charger_err_created_899fc4" ON "charger_error" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_charger_err_connect_4dce35" ON "charger_error" ("connector_id");
CREATE INDEX IF NOT EXISTS "idx_charger_err_error_c_442d7a" ON "charger_error" ("error_code");
CREATE INDEX IF NOT EXISTS "idx_charger_err_vendor__7cedb4" ON "charger_error" ("vendor_error_code");
CREATE INDEX IF NOT EXISTS "idx_charger_err_is_reso_24ce73" ON "charger_error" ("is_resolved");
CREATE INDEX IF NOT EXISTS "idx_charger_err_charger_9bb768" ON "charger_error" ("charger_id");
COMMENT ON TABLE "charger_error" IS 'Stores error events from chargers received via OCPP StatusNotification.';
        CREATE TABLE IF NOT EXISTS "admin_user" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "username" VARCHAR(255) NOT NULL UNIQUE,
    "hash_password" VARCHAR(255) NOT NULL,
    "is_superuser" BOOL NOT NULL DEFAULT False,
    "is_active" BOOL NOT NULL DEFAULT True,
    "email" VARCHAR(255),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_login" TIMESTAMPTZ
);
COMMENT ON TABLE "admin_user" IS 'Admin user for FastAdmin panel authentication';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "admin_user";
        DROP TABLE IF EXISTS "charger_error";"""
