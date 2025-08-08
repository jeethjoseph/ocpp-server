from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user" RENAME TO "app_user";
        ALTER TABLE "app_user" ADD "rfid_card_id" VARCHAR(255) UNIQUE;
        ALTER TABLE "app_user" ADD "preferred_language" VARCHAR(10) NOT NULL DEFAULT 'en';
        ALTER TABLE "app_user" ADD "terms_accepted_at" TIMESTAMPTZ;
        ALTER TABLE "app_user" ADD "clerk_user_id" VARCHAR(255) UNIQUE;
        ALTER TABLE "app_user" ADD "avatar_url" VARCHAR(500);
        ALTER TABLE "app_user" ADD "is_email_verified" BOOL NOT NULL DEFAULT False;
        ALTER TABLE "app_user" ADD "auth_provider" VARCHAR(6) NOT NULL DEFAULT 'CLERK';
        ALTER TABLE "app_user" ADD "notification_preferences" JSONB NOT NULL;
        ALTER TABLE "app_user" ADD "last_login" TIMESTAMPTZ;
        ALTER TABLE "app_user" ADD "role" VARCHAR(5) NOT NULL DEFAULT 'USER';
        ALTER TABLE "app_user" ALTER COLUMN "email" SET NOT NULL;
        DROP TABLE IF EXISTS "admin_user";
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_app_user_rfid_ca_c757c8" ON "app_user" ("rfid_card_id");
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_app_user_clerk_u_09f0ba" ON "app_user" ("clerk_user_id");
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_app_user_email_b12ac1" ON "app_user" ("email");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_app_user_email_b12ac1";
        DROP INDEX IF EXISTS "uid_app_user_clerk_u_09f0ba";
        DROP INDEX IF EXISTS "uid_app_user_rfid_ca_c757c8";
        ALTER TABLE "app_user" RENAME TO "user";
        ALTER TABLE "app_user" DROP COLUMN "rfid_card_id";
        ALTER TABLE "app_user" DROP COLUMN "preferred_language";
        ALTER TABLE "app_user" DROP COLUMN "terms_accepted_at";
        ALTER TABLE "app_user" DROP COLUMN "clerk_user_id";
        ALTER TABLE "app_user" DROP COLUMN "avatar_url";
        ALTER TABLE "app_user" DROP COLUMN "is_email_verified";
        ALTER TABLE "app_user" DROP COLUMN "auth_provider";
        ALTER TABLE "app_user" DROP COLUMN "notification_preferences";
        ALTER TABLE "app_user" DROP COLUMN "last_login";
        ALTER TABLE "app_user" DROP COLUMN "role";
        ALTER TABLE "app_user" ALTER COLUMN "email" DROP NOT NULL;"""
