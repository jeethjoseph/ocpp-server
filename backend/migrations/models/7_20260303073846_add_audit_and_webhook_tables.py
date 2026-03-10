from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "audit_log" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "actor_type" VARCHAR(20) NOT NULL,
    "actor_id" INT,
    "actor_email" VARCHAR(255),
    "action" VARCHAR(100) NOT NULL,
    "entity_type" VARCHAR(50) NOT NULL,
    "entity_id" VARCHAR(255) NOT NULL,
    "changes" JSONB
);
CREATE INDEX IF NOT EXISTS "idx_audit_log_created_277f5d" ON "audit_log" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_audit_log_action_286eba" ON "audit_log" ("action");
CREATE INDEX IF NOT EXISTS "idx_audit_log_entity__8af66a" ON "audit_log" ("entity_type");
CREATE INDEX IF NOT EXISTS "idx_audit_log_entity__5a16f1" ON "audit_log" ("entity_id");
        COMMENT ON COLUMN "firmware_update"."status" IS 'PENDING: PENDING
DOWNLOADING: DOWNLOADING
DOWNLOADED: DOWNLOADED
INSTALLING: INSTALLING
INSTALLED: INSTALLED
DOWNLOAD_FAILED: DOWNLOAD_FAILED
INSTALLATION_FAILED: INSTALLATION_FAILED
CANCELLED: CANCELLED';
        CREATE TABLE IF NOT EXISTS "webhook_event" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "source" VARCHAR(8) NOT NULL,
    "event_type" VARCHAR(100) NOT NULL,
    "event_id" VARCHAR(255),
    "payload" JSONB,
    "status" VARCHAR(20) NOT NULL DEFAULT 'processed',
    "error_message" TEXT
);
CREATE INDEX IF NOT EXISTS "idx_webhook_eve_created_7bb9b8" ON "webhook_event" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_webhook_eve_source_403572" ON "webhook_event" ("source");
CREATE INDEX IF NOT EXISTS "idx_webhook_eve_event_t_acfb90" ON "webhook_event" ("event_type");
CREATE INDEX IF NOT EXISTS "idx_webhook_eve_event_i_39bfe2" ON "webhook_event" ("event_id");
COMMENT ON COLUMN "webhook_event"."source" IS 'CLERK: CLERK\nRAZORPAY: RAZORPAY';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        COMMENT ON COLUMN "firmware_update"."status" IS 'PENDING: PENDING
DOWNLOADING: DOWNLOADING
DOWNLOADED: DOWNLOADED
INSTALLING: INSTALLING
INSTALLED: INSTALLED
DOWNLOAD_FAILED: DOWNLOAD_FAILED
INSTALLATION_FAILED: INSTALLATION_FAILED';
        DROP TABLE IF EXISTS "audit_log";
        DROP TABLE IF EXISTS "webhook_event";"""
