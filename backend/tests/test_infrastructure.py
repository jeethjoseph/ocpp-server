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
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        
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
        
        try:
            await redis_manager.connect()
            
            # Test basic operations
            test_charger_id = "test-charger-infra"
            connection_data = {
                "connected_at": "2025-01-01T00:00:00Z",
                "last_seen": "2025-01-01T00:00:00Z"
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