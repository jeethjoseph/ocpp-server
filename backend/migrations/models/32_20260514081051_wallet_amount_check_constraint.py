from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Enforce non-negative wallet_transaction.amount on new inserts.
        -- NOT VALID: historical CHARGE_DEDUCT rows (currently stored as
        -- negative amounts by convention) are not re-validated here.
        -- Module C's migration normalises history and redeems this
        -- constraint to VALID once the log is sign-consistent.
        ALTER TABLE "wallet_transaction"
          ADD CONSTRAINT "wallet_transaction_amount_non_negative"
          CHECK (amount >= 0) NOT VALID;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "wallet_transaction"
          DROP CONSTRAINT IF EXISTS "wallet_transaction_amount_non_negative";"""
