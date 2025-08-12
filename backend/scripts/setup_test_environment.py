#!/usr/bin/env python3
"""
Unified test environment setup script
Handles database setup, Redis testing, and integration test data
"""

import asyncio
import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_redis():
    """Test Redis connectivity"""
    try:
        import redis.asyncio as redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(redis_url, decode_responses=True)
        await client.ping()
        await client.aclose()
        logger.info("✅ Redis is available")
        return True
    except Exception as e:
        logger.warning(f"⚠️  Redis not available: {e}")
        return False

async def test_database():
    """Test database connectivity"""
    try:
        from database import init_db, close_db
        await init_db()
        await close_db()
        logger.info("✅ Database is available")
        return True
    except Exception as e:
        logger.warning(f"⚠️  Database not available: {e}")
        return False

async def setup_integration_test_data():
    """Setup integration test chargers if they don't exist"""
    try:
        from database import init_db, close_db
        from models import ChargingStation, Charger, Connector
        
        await init_db()
        
        # Get or create a test station
        station = await ChargingStation.filter(name__icontains="test").first()
        if not station:
            station = await ChargingStation.all().first()
        
        if not station:
            logger.warning("⚠️  No station found. Create a station first for integration tests.")
            await close_db()
            return False
        
        # Integration test charger IDs
        test_charger_ids = ["test-cp-2", "cp-1", "cp-2", "cp-3", "test-cp-boot"]
        created_count = 0
        
        for cp_id in test_charger_ids:
            existing = await Charger.filter(charge_point_string_id=cp_id).first()
            if not existing:
                charger = await Charger.create(
                    charge_point_string_id=cp_id,
                    station_id=station.id,
                    name=f"Integration Test Charger {cp_id}",
                    model="Test Model",
                    vendor="Test Vendor", 
                    serial_number=f"INTEG-{cp_id.replace('-', '').upper()}",
                    latest_status="UNAVAILABLE"
                )
                
                await Connector.create(
                    charger_id=charger.id,
                    connector_id=1,
                    connector_type="Type2",
                    max_power_kw=22.0
                )
                created_count += 1
        
        if created_count > 0:
            logger.info(f"✅ Created {created_count} integration test chargers")
        else:
            logger.info("✅ Integration test chargers already exist")
        
        await close_db()
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to setup integration test data: {e}")
        return False

async def main():
    """Main setup function"""
    logger.info("🔧 Setting up test environment...")
    
    # Test infrastructure
    redis_ok = await test_redis()
    db_ok = await test_database()
    
    if not redis_ok:
        logger.info("💡 To install Redis:")
        logger.info("   macOS: brew install redis && brew services start redis") 
        logger.info("   Ubuntu: sudo apt-get install redis-server")
        logger.info("   Docker: docker run -d -p 6379:6379 redis:alpine")
    
    if not db_ok:
        logger.info("💡 Database setup required - check your .env file and database configuration")
    
    # Setup integration test data if database is available
    if db_ok:
        await setup_integration_test_data()
    
    logger.info("🏁 Test environment setup complete!")
    
    if redis_ok and db_ok:
        logger.info("✅ Ready to run all tests with native pytest:")
        logger.info("   Unit tests (fast):         pytest -m unit")
        logger.info("   Infrastructure tests:      pytest -m infrastructure") 
        logger.info("   Integration tests:          pytest -m integration (requires server running)")
        logger.info("   All tests except slow:      pytest -m 'not slow'")
        logger.info("   Complete test suite:        pytest")
    else:
        logger.info("⚠️  Some tests may be skipped due to missing infrastructure")
        logger.info("💡 Use 'pytest -m unit' to run tests that don't require external services")

if __name__ == "__main__":
    asyncio.run(main())