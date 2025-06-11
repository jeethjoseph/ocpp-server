import os
from dotenv import load_dotenv

from tortoise import Tortoise
from tortoise.contrib.fastapi import register_tortoise

load_dotenv()

# Use credential-based config instead of URL string
TORTOISE_ORM = {
    "connections": {
        "default": {
            "engine": "tortoise.backends.asyncpg",  # or tortoise.backends.psycopg if using psycopg
            "credentials": {
                "host": os.environ.get("DB_HOST"),
                "port": int(os.environ.get("DB_PORT", 5432)),
                "user": os.environ.get("DB_USER"),
                "password": os.environ.get("DB_PASSWORD"),
                "database": os.environ.get("DB_NAME"),
                "ssl": "require", 
            }
        }
    },
    "apps": {
        "models": {
            "models": ["models"],
            "default_connection": "default",
        },
    },
}

async def init_db():
    """Initialize database connection"""
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()

async def close_db():
    """Close database connection"""
    await Tortoise.close_connections()

def register_tortoise_app(app):
    """Register Tortoise ORM with FastAPI app"""
    register_tortoise(
        app,
        config=TORTOISE_ORM,  # Use config instead of db_url
        generate_schemas=True,
        add_exception_handlers=True,
    )