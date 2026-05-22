from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Drop the INCLUDE clause from idx_wallet_txn_balance.
        -- The SUM in WalletService.get_balance also reads
        -- payment_metadata->>'status' for the TOP_UP filter, which is not
        -- in the index — so Postgres always heap-fetches anyway. Carrying
        -- amount + type in the index is dead weight on disk with no plan
        -- benefit. Plain (wallet_id) is sufficient.
        DROP INDEX IF EXISTS "idx_wallet_txn_balance";
        CREATE INDEX IF NOT EXISTS "idx_wallet_txn_balance"
            ON "wallet_transaction" (wallet_id);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_wallet_txn_balance";
        CREATE INDEX IF NOT EXISTS "idx_wallet_txn_balance"
            ON "wallet_transaction" (wallet_id) INCLUDE (amount, type);"""
