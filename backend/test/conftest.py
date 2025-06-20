# tests/conftest.py
"""
Shared pytest configuration and fixtures for all tests
"""
import os
import pytest
from typing import Generator
from tortoise import Tortoise

# Override database settings for tests
os.environ["DB_NAME"] = "test_ocpp_db"
os.environ["TESTING"] = "true"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def initialize_tests():
    """Initialize test database once for all tests"""
    await Tortoise.init(
        db_url=os.environ.get("TEST_DB_URL", "postgres://user:pass@localhost:5432/test_ocpp_db"),
        modules={"models": ["models"]}
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()

# Add this to your existing conftest.py or create if not exists
pytest_plugins = [
    "pytest_asyncio",
]