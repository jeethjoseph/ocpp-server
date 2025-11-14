from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "firmware_file" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "version" VARCHAR(50) NOT NULL UNIQUE,
    "filename" VARCHAR(255) NOT NULL,
    "file_path" VARCHAR(500) NOT NULL,
    "file_size" BIGINT NOT NULL,
    "checksum" VARCHAR(64) NOT NULL,
    "description" TEXT,
    "is_active" BOOL NOT NULL DEFAULT True,
    "uploaded_by_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_firmware_fi_version_6a3a58" ON "firmware_file" ("version");
        CREATE TABLE IF NOT EXISTS "firmware_update" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "status" VARCHAR(19) NOT NULL DEFAULT 'PENDING',
    "initiated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "download_url" VARCHAR(500) NOT NULL,
    "started_at" TIMESTAMPTZ,
    "completed_at" TIMESTAMPTZ,
    "error_message" TEXT,
    "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE,
    "firmware_file_id" INT NOT NULL REFERENCES "firmware_file" ("id") ON DELETE CASCADE,
    "initiated_by_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_firmware_up_status_023c31" ON "firmware_update" ("status");
CREATE INDEX IF NOT EXISTS "idx_firmware_up_charger_fa4ac6" ON "firmware_update" ("charger_id");
COMMENT ON COLUMN "firmware_update"."status" IS 'PENDING: PENDING\nDOWNLOADING: DOWNLOADING\nDOWNLOADED: DOWNLOADED\nINSTALLING: INSTALLING\nINSTALLED: INSTALLED\nDOWNLOAD_FAILED: DOWNLOAD_FAILED\nINSTALLATION_FAILED: INSTALLATION_FAILED';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "firmware_update";
        DROP TABLE IF EXISTS "firmware_file";"""
