from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE INDEX IF NOT EXISTS "idx_log_message_e28b80" ON "log" ("message_type", "timestamp");
        CREATE INDEX IF NOT EXISTS "idx_log_charge__e6d1d2" ON "log" ("charge_point_id", "timestamp");
        CREATE INDEX IF NOT EXISTS "idx_log_timesta_7cff2c" ON "log" ("timestamp");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_log_timesta_7cff2c";
        DROP INDEX IF EXISTS "idx_log_charge__e6d1d2";
        DROP INDEX IF EXISTS "idx_log_message_e28b80";"""
