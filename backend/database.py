import os
from dotenv import load_dotenv

from tortoise import Tortoise
from tortoise.contrib.fastapi import register_tortoise

from db_ssl import get_ssl_config

load_dotenv()

# Detect environment for SSL configuration
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

# SSL: driven by DB_SSL_MODE env var with sensible fallback for local dev.
# See backend/db_ssl.py for the contract.
ssl_config = get_ssl_config()

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