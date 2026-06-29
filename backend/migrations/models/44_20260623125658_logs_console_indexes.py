from tortoise import BaseDBAsyncClient

# ⚠️ PROD/STAGING DEPLOY HAZARD — `log` is the hottest write table (one row per
# OCPP frame). These plain `CREATE INDEX` statements take a write-blocking lock
# for the full build, stalling OCPP ingestion on a large existing table. They
# run inside Aerich's migration transaction, so `CONCURRENTLY` cannot go here.
# BEFORE running `aerich upgrade` on staging/prod, build the same indexes
# CONCURRENTLY (non-blocking) so these become no-ops:
#     make staging-create-log-indexes   (then make staging-migrate)
#     make prod-create-log-indexes      (then make prod-migrate)
# The index names below MUST stay in sync with that Makefile target. On fresh /
# dev DBs the `log` table is small, so running this migration directly is fine.


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
