from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_audit_log_entity__8af66a";
        CREATE INDEX IF NOT EXISTS "idx_audit_log_entity__d7945b" ON "audit_log" ("entity_type", "entity_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_audit_log_entity__d7945b";
        CREATE INDEX IF NOT EXISTS "idx_audit_log_entity__8af66a" ON "audit_log" ("entity_type");"""
