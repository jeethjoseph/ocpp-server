import os
from dotenv import load_dotenv

load_dotenv()

# Detect environment for SSL configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT.lower() in ["production", "prod"]

# SSL configuration: always require for cloud databases like Neon
db_host = os.getenv("DB_HOST", "localhost")
is_cloud_db = any(provider in db_host for provider in ["neon.tech", "aws.com", "gcp.com", "azure.com"])
ssl_config = "require" if (IS_PRODUCTION or is_cloud_db) else "disable"

TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",
            "credentials": {
                "host": os.getenv("DB_HOST"),
                "port": int(os.getenv("DB_PORT", 5432)),
                "user": os.getenv("DB_USER"),
                "password": os.getenv("DB_PASSWORD"),
                "database": os.getenv("DB_NAME"),
                "ssl": ssl_config,  # Environment-aware SSL
            }
        }
    },
    "apps": {
        "models": {
            "models": [
                "models",  
                "aerich.models" 
            ],
            "default_connection": "default",
        },
    },
}
