from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "diagnostic_bundle" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "epoch" INT NOT NULL DEFAULT 0,
    "bundle_seq" INT NOT NULL,
    "boot" INT,
    "first_record" INT,
    "last_record" INT,
    "overflow" INT,
    "overflow_delta" INT NOT NULL DEFAULT 0,
    "gap_records" INT NOT NULL DEFAULT 0,
    "s3_key" VARCHAR(512) NOT NULL,
    "size_bytes" INT NOT NULL,
    "line_count" INT NOT NULL DEFAULT 0,
    "header_valid" BOOL NOT NULL DEFAULT True,
    "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_diagnostic__charger_7db1f0" UNIQUE ("charger_id", "epoch", "bundle_seq")
);
CREATE INDEX IF NOT EXISTS "idx_diagnostic__created_2ca073" ON "diagnostic_bundle" ("created_at");
CREATE INDEX IF NOT EXISTS "idx_diagnostic__charger_418007" ON "diagnostic_bundle" ("charger_id");
COMMENT ON TABLE "diagnostic_bundle" IS 'One Diagnostic Bundle upload — the index over the S3 archive (ADR 0029).';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "diagnostic_bundle";"""
