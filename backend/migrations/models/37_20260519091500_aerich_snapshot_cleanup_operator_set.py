"""Aerich snapshot cleanup — flush the `operator_set_all_in_at` ghost.

Background: migration 36's original auto-generated form added BOTH
`tariff_per_kwh_all_in` AND `operator_set_all_in_at` to the `tariff` table.
The `operator_set_all_in_at` column was removed from the model and from
migration 36's body via a hand-edit during the qr-billing-overhaul review
cleanup. The hand-edit did NOT touch the snapshot Aerich stored in
`aerich.content` for migration 36 — so every subsequent `aerich migrate`
diffed against that stale snapshot and re-emitted the cleanup as an
unrelated DROP COLUMN in the next migration.

This migration's sole purpose is to APPLY the cleanup as a first-class
migration so Aerich writes a fresh, clean snapshot from the current model
state into the aerich row for migration 37. Future `aerich migrate` calls
will diff against this clean snapshot.

`IF EXISTS` makes the DROP safe across all environments:
  - dev:     column already manually dropped → no-op
  - staging: column never existed (post-revert migration 36 deployed) → no-op
  - prod:    column never existed → no-op

See `feedback_aerich_snapshot_poisoning.md` for the full RCA.
"""
from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "tariff" DROP COLUMN IF EXISTS "operator_set_all_in_at";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "tariff" ADD COLUMN IF NOT EXISTS "operator_set_all_in_at" TIMESTAMPTZ;"""
