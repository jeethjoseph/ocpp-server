# tests/conftest.py
import pytest
import asyncio
import redis.asyncio as redis
import os
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise
from unittest.mock import patch, AsyncMock
from typing import AsyncGenerator

import sys
import os
# Add parent directory to path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, connected_charge_points
from models import ChargingStation, Charger, Connector, Transaction, OCPPLog, User, VehicleProfile

# Test database configuration
TEST_DB_URL = "postgres://test_user:test_pass@localhost:5432/test_ocpp_db"

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with mocked Redis"""
    # Mock Redis manager for all tests
    with patch('routers.chargers.redis_manager') as mock_redis:
        # Use dynamic approach to check what's in connected_charge_points
        async def mock_get_all_connected():
            return list(connected_charge_points.keys())
        
        async def mock_is_connected(charger_id):
            return charger_id in connected_charge_points
        
        mock_redis.get_all_connected_chargers = mock_get_all_connected
        mock_redis.is_charger_connected = mock_is_connected
        mock_redis.connect = AsyncMock(return_value=None)
        mock_redis.disconnect = AsyncMock(return_value=None)
        mock_redis.add_connected_charger = AsyncMock(return_value=True)
        mock_redis.remove_connected_charger = AsyncMock(return_value=True)
        mock_redis.get_charger_connected_at = AsyncMock(return_value=None)
        
        # Initialize test database
        config = {
            "connections": {"default": TEST_DB_URL},
            "apps": {
                "models": {
                    "models": ["models"],
                    "default_connection": "default",
                }
            },
        }
        await Tortoise.init(config=config)
        await Tortoise.generate_schemas()
        
        # Clean up database before each test
        await Transaction.all().delete()
        await Connector.all().delete()
        await Charger.all().delete()
        await ChargingStation.all().delete()
        await OCPPLog.all().delete()
        connected_charge_points.clear()
        
        async with AsyncClient(
            transport=ASGITransport(app=app), 
            base_url="http://test"
        ) as ac:
            yield ac
        
        await Tortoise.close_connections()

# Test data fixtures
@pytest.fixture
async def test_station():
    """Create a test station"""
    return await ChargingStation.create(
        name="Test Station",
        latitude=12.9716,
        longitude=77.5946,
        address="Test Address"
    )

@pytest.fixture
async def test_charger(test_station):
    """Create a test charger"""
    import uuid
    charger = await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=test_station.id,
        name="Test Charger",
        model="Model X",
        vendor="Vendor Y",
        serial_number="SN12345",
        latest_status="AVAILABLE"
    )
    # Create connectors
    await Connector.create(
        charger_id=charger.id,
        connector_id=1,
        connector_type="Type2",
        max_power_kw=22.0
    )
    return charger

@pytest.fixture
async def test_user():
    """Create a test user with a unique phone number"""
    import random
    phone_number = f"9{random.randint(100000000, 999999999)}"
    return await User.create(phone_number=phone_number)

@pytest.fixture
async def test_vehicle(test_user):
    """Create a test vehicle profile for the user"""
    return await VehicleProfile.create(user=test_user)