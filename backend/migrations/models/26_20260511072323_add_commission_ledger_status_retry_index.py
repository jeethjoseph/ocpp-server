"""Add composite index on commission_ledger_entry for the retry sweep query.

Index supports the predicate used by ``retry_failed_transfers``:
``settlement_status IN (FAILED, ON_HOLD) AND retry_count < N``.

Safety on rollout
-----------------
This migration uses plain ``CREATE INDEX`` (not ``CONCURRENTLY``). Aerich wraps
``upgrade()`` in a transaction and ``CREATE INDEX CONCURRENTLY`` cannot run in
a transaction, so the non-concurrent form is required inside the migration.

On THIS branch's rollout the lock is a non-issue: ``commission_ledger_entry``
was introduced in migration #16 (April 2026) and is empty on every existing
production database — the table won't have rows until the franchisee module
ships. Index build on an empty table is sub-millisecond.

If you ever need to re-apply this on a populated table (snapshot replay,
disaster-recovery rebuild, etc.):
  1. Connect to the DB and run
     ``CREATE INDEX CONCURRENTLY IF NOT EXISTS "idx_commission__settlem_757ca1"
       ON "commission_ledger_entry" ("settlement_status", "retry_count");``
  2. Then ``aerich upgrade`` — the ``IF NOT EXISTS`` guard below makes this a
     no-op, so the migration table advances without re-running CREATE INDEX.
"""
from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE INDEX IF NOT EXISTS "idx_commission__settlem_757ca1" ON "commission_ledger_entry" ("settlement_status", "retry_count");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_commission__settlem_757ca1";"""
