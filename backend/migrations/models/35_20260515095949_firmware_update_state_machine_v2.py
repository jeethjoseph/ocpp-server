from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "firmware_file" ADD "s3_key" VARCHAR(500);
        ALTER TABLE "firmware_update" ADD "last_attempt_at" TIMESTAMPTZ;
        ALTER TABLE "firmware_update" ADD "next_retry_at" TIMESTAMPTZ;
        ALTER TABLE "firmware_update" RENAME COLUMN "retry_count" TO "attempt_count";
        ALTER TABLE "firmware_update" ALTER COLUMN "status" TYPE VARCHAR(9) USING "status"::VARCHAR(9);
        COMMENT ON COLUMN "firmware_update"."status" IS 'PENDING: PENDING
INSTALLED: INSTALLED
FAILED: FAILED
CANCELLED: CANCELLED';
        CREATE INDEX IF NOT EXISTS "idx_firmware_up_next_re_add09b" ON "firmware_update" ("next_retry_at");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_firmware_up_next_re_add09b";
        ALTER TABLE "firmware_file" DROP COLUMN "s3_key";
        ALTER TABLE "firmware_update" RENAME COLUMN "attempt_count" TO "retry_count";
        ALTER TABLE "firmware_update" DROP COLUMN "last_attempt_at";
        ALTER TABLE "firmware_update" DROP COLUMN "next_retry_at";
        COMMENT ON COLUMN "firmware_update"."status" IS 'PENDING: PENDING
DOWNLOADING: DOWNLOADING
DOWNLOADED: DOWNLOADED
INSTALLING: INSTALLING
INSTALLED: INSTALLED
DOWNLOAD_FAILED: DOWNLOAD_FAILED
INSTALLATION_FAILED: INSTALLATION_FAILED
CANCELLED: CANCELLED';
        ALTER TABLE "firmware_update" ALTER COLUMN "status" TYPE VARCHAR(19) USING "status"::VARCHAR(19);"""
