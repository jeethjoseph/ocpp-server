import os

from tortoise import BaseDBAsyncClient

# Backfill every charger's Asset Code and Purpose, then make the code mandatory
# (ADR 0028, slice 03).
#
# THE MAP IS EXPLICIT DATA, NOT A DERIVATION. `upgrade()` never reads
# Charger.name. The map below was generated offline from
# .scratch/charger-asset-code/asset-code-assignments.csv and is baked in as
# literal rows, so what a reviewer reads is exactly what executes. A derivation
# would re-read `name` at run time — and `name` is free-form, nullable and has
# no write-side validation anywhere, so anyone editing it between review and
# deploy would silently change the result. This migration is the last time
# anything in this codebase trusts `name`.
#
# KEYED ON charge_point_string_id, NEVER Charger.id. Row ids differ per register
# (production 25-38, staging 1-10) and can be reused if a row is deleted and
# recreated. The UUID is immutable and unique.
#
# The seed is the one deliberate exception to the Asset Code being unrelated to
# `name`: production's fleet already carries VOW#### stencils, so seeding keeps
# the paint valid and avoids the wrong-answer bug that pure id-order allocation
# would cause (six of production's eight painted units would shift, and a
# customer quoting VOW0006 would resolve to a different charger at the same
# station).
#
# Gaps stay gaps. Production has no VOW0004/VOW0005 because those two units sit
# at the staging site; they are not backfilled, and production's next new unit
# is VOW0016.
#
# DEVELOPMENT IS DELIBERATELY NOT MAPPED. A local database holds arbitrary
# chargers, so dev (and any unrecognised environment) allocates sequentially
# instead of requiring a map. Otherwise every dev box breaks on migrate. The
# series CHECK from migration 58 still applies, so an unrecognised environment
# can only ever mint VOWS codes.

ASSET_CODE_BACKFILL = {
    "production": {
        "7536bc02-dff1-469c-bc51-20ca44a462a7": ("VOW0001", "PUBLIC"),  # VOW0001 @ IDofThings
        "d2bd7faa-22ad-495d-9cd3-ada154ee316f": ("VOW0002", "PUBLIC"),  # VOW0002 @ IDofThings
        "21fa9af6-4ec8-47ed-8961-b757b3035c7a": ("VOW0003", "PUBLIC"),  # VOW0003 @ Seleno Stones
        "ba1e2d83-d22c-4654-a877-3e82238e12bd": ("VOW0006", "PUBLIC"),  # VOW0006 @ SARADHY TOWERS
        "b226ca5e-d5cf-4404-9f4f-25d228493ee2": ("VOW0007", "PUBLIC"),  # VOW0007 @ SARADHY TOWERS
        "f2f6a6a5-69e7-47e1-9611-72df4964e29d": ("VOW0008", "PUBLIC"),  # VOW0008 @ SK EV Charging Station
        "a9bebd86-90e2-4bba-bf3d-64619bf23a9f": ("VOW0009", "PUBLIC"),  # VOW0009 @ SK EV Charging Station
        "14b21333-73d3-4c79-9322-7563efcf591f": ("VOW0010", "PUBLIC"),  # VOW0010 @ SK EV Charging Station
        "a623d346-98b6-45b3-9546-ec024ebf54cc": ("VOW0011", "TEST"),  # V3C_Test @ IDofThings
        "a0ce4b7d-16fd-4929-ba71-576067f99ab0": ("VOW0012", "TEST"),  # V7C_Test @ IDofThings
        "f0e18fee-8a92-4f54-8558-616b1683ec0a": ("VOW0013", "TEST"),  # Chargemode_1 @ IDofThings
        "01873711-1b3e-402f-b6f4-c0bec8a04fa4": ("VOW0014", "TEST"),  # Staging_VOW0002 @ IDofThings
        "9ad4c552-a901-49fe-8f61-00a6904bb1f2": ("VOW0015", "TEST"),  # Staging_VOW0004 @ IDofThings
    },
    "staging": {
        "ffeadb01-78bc-4b6e-b5cd-1ff657cbedbc": ("VOWS0001", "PUBLIC"),  # VOW0001 @ IDT_Staging
        "8964a6e8-cb46-48b0-ae86-cdbc67d5a634": ("VOWS0002", "PUBLIC"),  # VOW0002 @ IDT_Staging
        "23a9345c-29bf-4169-b92f-55f7139568a0": ("VOWS0004", "PUBLIC"),  # VOW0004 @ IDT_Staging
        "6a8394f8-dc2d-4cbb-8336-7d174ae6ccd3": ("VOWS0005", "PUBLIC"),  # VOW0005 @ IDT_Staging
        "ed2bd339-c8cc-44ef-8e8a-710ab61141a5": ("VOWS0006", "TEST"),  # V3C_Test @ IDT_Staging
        "e69ca119-2a05-4db7-9159-da4950ee4103": ("VOWS0007", "TEST"),  # V7C_Test @ IDT_Staging
        "8fc4b8a2-3637-498b-b469-d08e36cee38d": ("VOWS0008", "TEST"),  # V3C_Test1 @ IDT_Staging
        "f92c399a-82a3-4d70-95b7-397fe584dbe4": ("VOWS0009", "TEST"),  # V7C_Test2 @ IDT_Staging
        "e5d994b1-4385-4ac9-ad06-5f00fe1955f2": ("VOWS0010", "TEST"),  # Chargemode_1 @ IDT_Staging
    },
}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _mapped_upgrade(mapping: dict) -> str:
    """Backfill from the explicit map, guarding every assumption.

    Four guards, each RAISING rather than skipping quietly. A migration that
    silently does less than it claims is worse than one that fails: the flip to
    NOT NULL would surface the shortfall as a confusing constraint violation
    with no clue which rows were missed.
    """
    values = ",\n            ".join(
        f"({_sql_literal(uuid_)}, {_sql_literal(code)}, {_sql_literal(purpose)})"
        for uuid_, (code, purpose) in mapping.items()
    )
    return f"""
        CREATE TEMP TABLE "_asset_code_map" (
            "ocpp_id" TEXT PRIMARY KEY, "code" TEXT NOT NULL, "purpose" TEXT NOT NULL
        );
        INSERT INTO "_asset_code_map" ("ocpp_id", "code", "purpose") VALUES
            {values};

        -- Guard 1: every UUID in the map exists in this register. A miss means
        -- the map was built against the wrong environment, and continuing
        -- would silently under-fill.
        DO $$
        DECLARE unknown_ids TEXT;
        BEGIN
            SELECT string_agg(m."ocpp_id", ', ') INTO unknown_ids
            FROM "_asset_code_map" m
            LEFT JOIN "charger" c ON c."charge_point_string_id" = m."ocpp_id"
            WHERE c."id" IS NULL;
            IF unknown_ids IS NOT NULL THEN
                RAISE EXCEPTION 'Asset Code backfill: map names chargers absent from this register: %', unknown_ids;
            END IF;
        END $$;

        -- Guard 2: every row still needing a code is covered by the map. This
        -- is what catches a charger created between CSV generation and deploy
        -- — the one failure mode a reviewed map cannot see coming.
        DO $$
        DECLARE uncovered TEXT;
        BEGIN
            SELECT string_agg(c."charge_point_string_id", ', ') INTO uncovered
            FROM "charger" c
            LEFT JOIN "_asset_code_map" m ON c."charge_point_string_id" = m."ocpp_id"
            WHERE c."asset_code" IS NULL AND m."ocpp_id" IS NULL;
            IF uncovered IS NOT NULL THEN
                RAISE EXCEPTION 'Asset Code backfill: chargers not covered by the map: %', uncovered;
            END IF;
        END $$;

        -- Guard 3: only rows without a code are written, so a re-run is a
        -- no-op rather than a UNIQUE violation, and an Asset Code already
        -- assigned is never silently reassigned.
        UPDATE "charger" c
           SET "asset_code" = m."code",
               "purpose" = m."purpose"
          FROM "_asset_code_map" m
         WHERE c."charge_point_string_id" = m."ocpp_id"
           AND c."asset_code" IS NULL;

        -- Guard 4: post-condition. Nothing may reach the NOT NULL flip without
        -- a code.
        DO $$
        DECLARE remaining INTEGER;
        BEGIN
            SELECT count(*) INTO remaining FROM "charger" WHERE "asset_code" IS NULL;
            IF remaining > 0 THEN
                RAISE EXCEPTION 'Asset Code backfill: % charger(s) still have no code', remaining;
            END IF;
        END $$;

        DROP TABLE "_asset_code_map";
        ALTER TABLE "charger" ALTER COLUMN "asset_code" SET NOT NULL;"""


def _sequential_upgrade(series: str) -> str:
    """Development and unrecognised environments: allocate in id order.

    No map, because a local database holds arbitrary chargers. `purpose` is
    left at its PUBLIC default — a dev box has no fleet to classify, and
    guessing would be the derivation this migration exists to avoid.
    """
    return f"""
        UPDATE "charger" c
           SET "asset_code" = '{series}' || lpad(seq."rn"::TEXT, 4, '0')
          FROM (
                SELECT "id", row_number() OVER (ORDER BY "id") AS "rn"
                  FROM "charger"
                 WHERE "asset_code" IS NULL
               ) seq
         WHERE c."id" = seq."id"
           AND c."asset_code" IS NULL;
        ALTER TABLE "charger" ALTER COLUMN "asset_code" SET NOT NULL;"""


async def upgrade(db: BaseDBAsyncClient) -> str:
    environment = (os.getenv("ENVIRONMENT", "development") or "").strip().lower()
    mapping = ASSET_CODE_BACKFILL.get(environment)
    if mapping is None:
        from policy import charger_code_series

        return _sequential_upgrade(charger_code_series(environment))
    return _mapped_upgrade(mapping)


async def downgrade(db: BaseDBAsyncClient) -> str:
    # The codes themselves are deliberately NOT cleared. Re-running the upgrade
    # is idempotent (guard 3), and clearing would destroy the mapping that a
    # subsequent re-upgrade would have to reconstruct from a CSV that may have
    # moved on.
    return """
        ALTER TABLE "charger" ALTER COLUMN "asset_code" DROP NOT NULL;"""
