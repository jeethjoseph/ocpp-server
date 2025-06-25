from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charger" ALTER COLUMN "latest_status" TYPE VARCHAR(13) USING "latest_status"::VARCHAR(13);
        COMMENT ON COLUMN "charger"."latest_status" IS 'AVAILABLE: Available
PREPARING: Preparing
CHARGING: Charging
SUSPENDED_EVSE: SuspendedEVSE
SUSPENDED_EV: SuspendedEV
FINISHING: Finishing
RESERVED: Reserved
UNAVAILABLE: Unavailable
FAULTED: Faulted';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        COMMENT ON COLUMN "charger"."latest_status" IS 'AVAILABLE: AVAILABLE
PREPARING: PREPARING
CHARGING: CHARGING
SUSPENDED_EVSE: SUSPENDED_EVSE
SUSPENDED_EV: SUSPENDED_EV
FINISHING: FINISHING
RESERVED: RESERVED
UNAVAILABLE: UNAVAILABLE
FAULTED: FAULTED';
        ALTER TABLE "charger" ALTER COLUMN "latest_status" TYPE VARCHAR(14) USING "latest_status"::VARCHAR(14);"""
