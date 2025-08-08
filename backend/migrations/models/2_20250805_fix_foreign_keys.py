from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Drop old foreign key constraints that point to the non-existent 'user' table
        ALTER TABLE "wallet" DROP CONSTRAINT IF EXISTS "wallet_user_id_fkey";
        ALTER TABLE "vehicle_profile" DROP CONSTRAINT IF EXISTS "vehicle_profile_user_id_fkey";
        ALTER TABLE "transaction" DROP CONSTRAINT IF EXISTS "transaction_user_id_fkey";
        
        -- Add new foreign key constraints pointing to 'app_user' table
        ALTER TABLE "wallet" ADD CONSTRAINT "wallet_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON DELETE CASCADE;
        ALTER TABLE "vehicle_profile" ADD CONSTRAINT "vehicle_profile_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON DELETE CASCADE;
        ALTER TABLE "transaction" ADD CONSTRAINT "transaction_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "app_user" ("id") ON DELETE CASCADE;
        """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        -- Drop new foreign key constraints
        ALTER TABLE "wallet" DROP CONSTRAINT IF EXISTS "wallet_user_id_fkey";
        ALTER TABLE "vehicle_profile" DROP CONSTRAINT IF EXISTS "vehicle_profile_user_id_fkey"; 
        ALTER TABLE "transaction" DROP CONSTRAINT IF EXISTS "transaction_user_id_fkey";
        
        -- Add old foreign key constraints pointing back to 'user' table (if it exists)
        -- Note: This downgrade assumes the user table has been renamed back
        ALTER TABLE "wallet" ADD CONSTRAINT "wallet_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON DELETE CASCADE;
        ALTER TABLE "vehicle_profile" ADD CONSTRAINT "vehicle_profile_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON DELETE CASCADE;
        ALTER TABLE "transaction" ADD CONSTRAINT "transaction_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "user" ("id") ON DELETE CASCADE;
        """