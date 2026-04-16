import os
from dotenv import load_dotenv

load_dotenv()

# Detect environment for SSL configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT.lower() in ["production", "prod"]

# SSL configuration: require for cloud/external DBs, disable for local/Docker
db_host = os.getenv("DB_HOST", "localhost")
is_local_db = db_host in ["localhost", "127.0.0.1", "postgres"]
ssl_config = "disable" if is_local_db else "require"

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
