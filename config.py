TORTOISE_ORM = {
    "connections": {"default": "sqlite://db.sqlite3"},  # or postgres://user:pass@host/db
    "apps": {
        "models": {
            "models": ["models.schema", "aerich.models"],  # aerich for migrations
            "default_connection": "default",
        }
    }
}
