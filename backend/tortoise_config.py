import os
from dotenv import load_dotenv

from db_ssl import get_ssl_config

load_dotenv()

# Detect environment for SSL configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT.lower() in ["production", "prod"]

# SSL: driven by DB_SSL_MODE env var with sensible fallback for local dev.
# See backend/db_ssl.py for the contract.
ssl_config = get_ssl_config()

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
