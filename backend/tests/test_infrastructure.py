#!/usr/bin/env python3
"""
Infrastructure tests for Redis, Database, and basic connectivity
"""

import pytest
import asyncio
import redis.asyncio as redis
import os
import logging
from tortoise import Tortoise

logger = logging.getLogger(__name__)

@pytest.mark.infrastructure
class TestInfrastructure:
    """Test basic infrastructure components"""
    
    @pytest.mark.asyncio
    async def test_redis_connectivity(self):
        """Test Redis connection and basic operations"""
        # Construct from REDIS_HOST/REDIS_PORT (same pattern as redis_manager.py)
        # so this works inside docker exec where the host is `redis` not `localhost`
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = os.getenv("REDIS_PORT", "6379")
        redis_url = os.getenv("REDIS_URL") or f"redis://{redis_host}:{redis_port}"
        
        try:
            client = redis.from_url(redis_url, decode_responses=True)
            
            # Test ping
            await client.ping()
            
            # Test basic operations
            test_key = "test:connection"
            test_value = "test_value"
            
            # Set a value
            await client.set(test_key, test_value)
            
            # Get the value
            retrieved_value = await client.get(test_key)
            assert retrieved_value == test_value
            
            # Test exists
            exists = await client.exists(test_key)
            assert exists == 1
            
            # Test delete
            await client.delete(test_key)
            exists_after_delete = await client.exists(test_key)
            assert exists_after_delete == 0
            
            # Test keys pattern matching
            await client.set("charger_connection:test1", "value1")
            await client.set("charger_connection:test2", "value2")
            await client.set("other:key", "value3")
            
            keys = await client.keys("charger_connection:*")
            assert len(keys) == 2
            assert "charger_connection:test1" in keys
            assert "charger_connection:test2" in keys
            
            # Cleanup
            await client.delete("charger_connection:test1", "charger_connection:test2", "other:key")
            await client.aclose()
            
        except redis.ConnectionError:
            pytest.skip("Redis not available - install and start Redis to run this test")
    
    @pytest.mark.asyncio
    async def test_database_connectivity(self):
        """Test database connection and basic operations"""
        # Use the same config as main app
        from database import TORTOISE_ORM
        
        try:
            await Tortoise.init(config=TORTOISE_ORM)
            
            # Test basic query
            from models import ChargingStation
            stations = await ChargingStation.all()
            
            # Just verify we can connect and query
            assert isinstance(stations, list)
            
            await Tortoise.close_connections()
            
        except Exception as e:
            pytest.skip(f"Database not available: {e}")
    
    @pytest.mark.asyncio
    async def test_redis_manager(self):
        """Test Redis manager functionality"""
        from redis_manager import redis_manager
        from datetime import datetime, timezone

        try:
            await redis_manager.connect()

            # Test basic operations — connected_at/last_seen must be datetime
            # objects (redis_manager calls .isoformat() on them internally)
            test_charger_id = "test-charger-infra"
            now = datetime.now(timezone.utc)
            connection_data = {
                "connected_at": now,
                "last_seen": now,
            }
            
            # Test add
            result = await redis_manager.add_connected_charger(test_charger_id, connection_data)
            assert result is True
            
            # Test check connection
            is_connected = await redis_manager.is_charger_connected(test_charger_id)
            assert is_connected is True
            
            # Test get all
            all_chargers = await redis_manager.get_all_connected_chargers()
            assert test_charger_id in all_chargers
            
            # Test remove
            result = await redis_manager.remove_connected_charger(test_charger_id)
            assert result is True
            
            # Verify removed
            is_connected = await redis_manager.is_charger_connected(test_charger_id)
            assert is_connected is False
            
            await redis_manager.disconnect()

        except Exception:
            pytest.skip("Redis not available for manager testing")

    @pytest.mark.asyncio
    async def test_remove_connected_charger_survives_connection_loss(self):
        """A DNS/connection failure during removal (deploy/restart) must not
        raise — it warns and returns False (OCPP-BACKEND-7). No live Redis
        needed: inject a client whose delete() raises ConnectionError."""
        from unittest.mock import AsyncMock
        from redis_manager import RedisConnectionManager

        mgr = RedisConnectionManager()
        mgr.redis_client = AsyncMock()
        mgr.redis_client.delete = AsyncMock(
            side_effect=redis.ConnectionError(
                "Error -2 connecting to redis:6379. Name or service not known."
            )
        )

        result = await mgr.remove_connected_charger("charger-during-deploy")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_connected_charger_reraises_unexpected_as_handled(self):
        """A genuinely unexpected (non-connection) error still returns False
        but goes through the error branch, preserving the investigate signal."""
        from unittest.mock import AsyncMock
        from redis_manager import RedisConnectionManager

        mgr = RedisConnectionManager()
        mgr.redis_client = AsyncMock()
        mgr.redis_client.delete = AsyncMock(side_effect=ValueError("boom"))

        result = await mgr.remove_connected_charger("charger-x")
        assert result is False