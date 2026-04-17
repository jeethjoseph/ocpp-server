from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charging_station" ADD "state" VARCHAR(100);
        ALTER TABLE "charging_station" ADD "state_code" VARCHAR(5);
        ALTER TABLE "charging_station" ADD "franchisee_id" INT;
        ALTER TABLE "charging_station" ADD "pincode" VARCHAR(10);
        ALTER TABLE "charging_station" ADD CONSTRAINT "fk_charging_franchis_815ce7da" FOREIGN KEY ("franchisee_id") REFERENCES "franchisee" ("id") ON DELETE SET NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "charging_station" DROP CONSTRAINT IF EXISTS "fk_charging_franchis_815ce7da";
        ALTER TABLE "charging_station" DROP COLUMN "state";
        ALTER TABLE "charging_station" DROP COLUMN "state_code";
        ALTER TABLE "charging_station" DROP COLUMN "franchisee_id";
        ALTER TABLE "charging_station" DROP COLUMN "pincode";"""
