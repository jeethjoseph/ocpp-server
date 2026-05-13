"""Shared helpers for dev seed scripts.

Centralizes the Tortoise config builder and a UTC `now()` so each seeder
doesn't reinvent them. Keep this file tiny — it's a helper, not a module.
"""

import os
from datetime import datetime, timezone


def build_tortoise_config() -> dict:
    """Construct a Tortoise config from DB_* env vars.

    Mirrors backend/database.py credentials style. Fails loud if any of the
    five required vars is missing — no silent fallbacks.
    """
    required = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required DB env vars: {', '.join(missing)}")
    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.asyncpg",
                "credentials": {
                    "host": os.environ["DB_HOST"],
                    "port": int(os.environ["DB_PORT"]),
                    "user": os.environ["DB_USER"],
                    "password": os.environ["DB_PASSWORD"],
                    "database": os.environ["DB_NAME"],
                    "ssl": "disable",
                },
            }
        },
        "apps": {
            "models": {
                "models": ["models", "aerich.models"],
                "default_connection": "default",
            },
        },
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
