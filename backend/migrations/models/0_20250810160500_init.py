from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "charging_station" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(255),
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "address" TEXT
);
CREATE TABLE IF NOT EXISTS "charger" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "charge_point_string_id" VARCHAR(255) NOT NULL UNIQUE,
    "name" VARCHAR(255),
    "model" VARCHAR(100),
    "vendor" VARCHAR(100),
    "serial_number" VARCHAR(100) UNIQUE,
    "firmware_version" VARCHAR(100),
    "iccid" VARCHAR(100),
    "imsi" VARCHAR(100),
    "meter_type" VARCHAR(100),
    "meter_serial_number" VARCHAR(100),
    "latest_status" VARCHAR(13) NOT NULL,
    "last_heart_beat_time" TIMESTAMPTZ,
    "station_id" INT NOT NULL REFERENCES "charging_station" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "charger"."latest_status" IS 'AVAILABLE: Available\nPREPARING: Preparing\nCHARGING: Charging\nSUSPENDED_EVSE: SuspendedEVSE\nSUSPENDED_EV: SuspendedEV\nFINISHING: Finishing\nRESERVED: Reserved\nUNAVAILABLE: Unavailable\nFAULTED: Faulted';
CREATE TABLE IF NOT EXISTS "connector" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connector_id" INT NOT NULL,
    "connector_type" VARCHAR(255) NOT NULL,
    "max_power_kw" DOUBLE PRECISION,
    "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_connector_charger_7d3bd9" UNIQUE ("charger_id", "connector_id")
);
CREATE TABLE IF NOT EXISTS "log" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "charge_point_id" VARCHAR(100),
    "message_type" VARCHAR(100),
    "direction" VARCHAR(3) NOT NULL,
    "payload" JSONB,
    "status" VARCHAR(50),
    "correlation_id" VARCHAR(100),
    "timestamp" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON COLUMN "log"."direction" IS 'INBOUND: IN\nOUTBOUND: OUT';
CREATE TABLE IF NOT EXISTS "payment_gateway" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "name" VARCHAR(100),
    "api_key" VARCHAR(255),
    "webhook_secret" VARCHAR(255),
    "status" BOOL NOT NULL DEFAULT True,
    "config" JSONB,
    "default_currency" VARCHAR(3) NOT NULL DEFAULT 'INR'
);
CREATE TABLE IF NOT EXISTS "tariff" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "rate_per_kwh" DECIMAL(5,2) NOT NULL,
    "is_global" BOOL NOT NULL DEFAULT False,
    "charger_id" INT REFERENCES "charger" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "app_user" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "email" VARCHAR(255) NOT NULL UNIQUE,
    "phone_number" VARCHAR(255) UNIQUE,
    "clerk_user_id" VARCHAR(255) UNIQUE,
    "auth_provider" VARCHAR(6) NOT NULL DEFAULT 'CLERK',
    "full_name" VARCHAR(255),
    "avatar_url" VARCHAR(500),
    "role" VARCHAR(5) NOT NULL DEFAULT 'USER',
    "is_active" BOOL NOT NULL DEFAULT True,
    "is_email_verified" BOOL NOT NULL DEFAULT False,
    "terms_accepted_at" TIMESTAMPTZ,
    "preferred_language" VARCHAR(10) NOT NULL DEFAULT 'en',
    "notification_preferences" JSONB NOT NULL,
    "rfid_card_id" VARCHAR(255) UNIQUE,
    "password_hash" VARCHAR(255),
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_login" TIMESTAMPTZ
);
COMMENT ON COLUMN "app_user"."auth_provider" IS 'EMAIL: EMAIL\nGOOGLE: GOOGLE\nCLERK: CLERK';
COMMENT ON COLUMN "app_user"."role" IS 'ADMIN: ADMIN\nUSER: USER';
CREATE TABLE IF NOT EXISTS "valid_vehicle_profile" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "make" VARCHAR(100),
    "model" VARCHAR(100),
    "year" INT
);
CREATE TABLE IF NOT EXISTS "vehicle_profile" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "make" VARCHAR(100),
    "model" VARCHAR(100),
    "year" INT,
    "user_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "transaction" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "start_meter_kwh" DOUBLE PRECISION,
    "end_meter_kwh" DOUBLE PRECISION,
    "energy_consumed_kwh" DOUBLE PRECISION,
    "start_time" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "end_time" TIMESTAMPTZ,
    "stop_reason" TEXT,
    "transaction_status" VARCHAR(13) NOT NULL,
    "charger_id" INT NOT NULL REFERENCES "charger" ("id") ON DELETE CASCADE,
    "user_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE CASCADE,
    "vehicle_id" INT REFERENCES "vehicle_profile" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "transaction"."transaction_status" IS 'STARTED: STARTED\nPENDING_START: PENDING_START\nRUNNING: RUNNING\nPENDING_STOP: PENDING_STOP\nSTOPPED: STOPPED\nCOMPLETED: COMPLETED\nCANCELLED: CANCELLED\nFAILED: FAILED';
CREATE TABLE IF NOT EXISTS "meter_value" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "reading_kwh" DOUBLE PRECISION NOT NULL,
    "current" DOUBLE PRECISION,
    "voltage" DOUBLE PRECISION,
    "power_kw" DOUBLE PRECISION,
    "transaction_id" INT NOT NULL REFERENCES "transaction" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "wallet" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "balance" DECIMAL(10,2),
    "user_id" INT NOT NULL UNIQUE REFERENCES "app_user" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "wallet_transaction" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "amount" DECIMAL(10,2) NOT NULL,
    "type" VARCHAR(13) NOT NULL,
    "description" TEXT,
    "payment_metadata" JSONB,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "charging_transaction_id" INT REFERENCES "transaction" ("id") ON DELETE CASCADE,
    "wallet_id" INT NOT NULL REFERENCES "wallet" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "wallet_transaction"."type" IS 'TOP_UP: TOP_UP\nCHARGE_DEDUCT: CHARGE_DEDUCT';
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
