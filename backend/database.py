import os
from dotenv import load_dotenv

from tortoise import Tortoise
from tortoise.contrib.fastapi import register_tortoise

load_dotenv()

# Detect environment for SSL configuration
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# SSL configuration: require for cloud/external DBs, disable for local/Docker
db_host = os.environ.get("DB_HOST", "localhost")
is_local_db = db_host in ["localhost", "127.0.0.1", "postgres"]
ssl_config = "disable" if is_local_db else "require"

# Use credential-based config instead of URL string
TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",
            "credentials": {
                "host": os.environ.get("DB_HOST"),
                "port": int(os.environ.get("DB_PORT", 5432)),
                "user": os.environ.get("DB_USER"),
                "password": os.environ.get("DB_PASSWORD"),
                "database": os.environ.get("DB_NAME"),
                "ssl": ssl_config,  # Environment-aware SSL
            }
        }
    },
    "apps": {
        "models": {
            "models": [
                "models",
                "admin",  # FastAdmin models
                "aerich.models"  # Migration tracking
            ],
            "default_connection": "default",
        },
    },
}

async def init_db():
    """Initialize database connection

    Note: Schema changes should be handled via Aerich migrations, not auto-generation.
    Run 'aerich upgrade' before starting the app in production.
    """
    await Tortoise.init(config=TORTOISE_ORM)
    # Don't auto-generate schemas - use Aerich migrations instead
    # await Tortoise.generate_schemas()

async def close_db():
    """Close database connection"""
    await Tortoise.close_connections()

def register_tortoise_app(app):
    """Register Tortoise ORM with FastAPI app

    Note: generate_schemas=False because we use Aerich migrations.
    """
    register_tortoise(
        app,
        config=TORTOISE_ORM,
        generate_schemas=False,  # Use Aerich migrations instead
        add_exception_handlers=True,
    )