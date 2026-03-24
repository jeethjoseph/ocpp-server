import redis.asyncio as redis
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, List
import os

logger = logging.getLogger(__name__)

class RedisConnectionManager:
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self.connection_key_prefix = "charger_connection:"
        
    async def connect(self):
        """Initialize Redis connection"""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            await self.redis_client.ping()
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Running in fallback mode without Redis.")
            self.redis_client = None
    
    async def disconnect(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")
    
    async def add_connected_charger(self, charger_id: str, connection_data: Dict):
        """Add a charger to the connected list"""
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return False
        
        try:
            # Store simple connection timestamp
            key = f"{self.connection_key_prefix}{charger_id}"
            connected_at = connection_data['connected_at'].isoformat()
            
            await self.redis_client.set(key, connected_at)
            
            logger.info(f"Added charger {charger_id} to Redis")
            return True
        except Exception as e:
            logger.error(f"Failed to add charger {charger_id} to Redis: {e}")
            return False
    
    async def remove_connected_charger(self, charger_id: str):
        """Remove a charger from the connected list"""
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return False
        
        try:
            connection_key = f"{self.connection_key_prefix}{charger_id}"
            await self.redis_client.delete(connection_key)
            
            logger.info(f"Removed charger {charger_id} from Redis")
            return True
        except Exception as e:
            logger.error(f"Failed to remove charger {charger_id} from Redis: {e}")
            return False
    
    
    async def is_charger_connected(self, charger_id: str) -> bool:
        """Check if a charger is currently connected"""
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return False
        
        try:
            key = f"{self.connection_key_prefix}{charger_id}"
            exists = await self.redis_client.exists(key)
            return bool(exists)
        except Exception as e:
            logger.error(f"Failed to check connection status for charger {charger_id}: {e}")
            return False
    
    
    async def get_all_connected_chargers(self) -> List[str]:
        """Get list of all connected charger IDs"""
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return []
        
        try:
            pattern = f"{self.connection_key_prefix}*"
            keys = await self.redis_client.keys(pattern)
            charger_ids = [key.replace(self.connection_key_prefix, "") for key in keys]
            return charger_ids
        except Exception as e:
            logger.error(f"Failed to get connected chargers: {e}")
            return []
    
    # QR session cache methods
    QR_SESSION_PREFIX = "qr_session:"

    async def set_qr_session(self, transaction_id: int, data: Dict, ttl: int = 86400) -> bool:
        """Cache QR session data for budget checking during MeterValues"""
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return False
        try:
            key = f"{self.QR_SESSION_PREFIX}{transaction_id}"
            await self.redis_client.set(key, json.dumps(data), ex=ttl)
            logger.info(f"Cached QR session for transaction {transaction_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cache QR session for transaction {transaction_id}: {e}")
            return False

    async def get_qr_session(self, transaction_id: int) -> Optional[Dict]:
        """Get cached QR session data"""
        if not self.redis_client:
            return None
        try:
            key = f"{self.QR_SESSION_PREFIX}{transaction_id}"
            data = await self.redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get QR session for transaction {transaction_id}: {e}")
            return None

    async def delete_qr_session(self, transaction_id: int) -> bool:
        """Delete QR session cache"""
        if not self.redis_client:
            return False
        try:
            key = f"{self.QR_SESSION_PREFIX}{transaction_id}"
            await self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete QR session for transaction {transaction_id}: {e}")
            return False

    # Socket charger grace period methods
    SOCKET_GRACE_PREFIX = "socket_grace:"

    async def set_socket_grace_period(
        self, charge_point_id: str, transaction_ids: list, ttl: int = 300
    ) -> bool:
        """Store grace period data for a socket charger reporting Available."""
        if not self.redis_client:
            return False
        try:
            key = f"{self.SOCKET_GRACE_PREFIX}{charge_point_id}"
            data = {
                "transaction_ids": transaction_ids,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.redis_client.set(key, json.dumps(data), ex=ttl)
            logger.info(f"Set socket grace period for {charge_point_id}, txns={transaction_ids}")
            return True
        except Exception as e:
            logger.error(f"Failed to set socket grace period for {charge_point_id}: {e}")
            return False

    async def get_socket_grace_period(self, charge_point_id: str) -> Optional[Dict]:
        """Get active grace period data for a socket charger."""
        if not self.redis_client:
            return None
        try:
            key = f"{self.SOCKET_GRACE_PREFIX}{charge_point_id}"
            data = await self.redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get socket grace period for {charge_point_id}: {e}")
            return None

    async def delete_socket_grace_period(self, charge_point_id: str) -> bool:
        """Clear grace period for a socket charger (e.g. MeterValues arrived)."""
        if not self.redis_client:
            return False
        try:
            key = f"{self.SOCKET_GRACE_PREFIX}{charge_point_id}"
            await self.redis_client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete socket grace period for {charge_point_id}: {e}")
            return False

    # QR transaction verification tokens
    QR_TXN_TOKEN_PREFIX = "qr_txn_token:"

    async def set_qr_txn_token(self, token: str, vpa: str, ttl: int = 600) -> bool:
        """Store a verification token for a VPA lookup session."""
        if not self.redis_client:
            return False
        try:
            key = f"{self.QR_TXN_TOKEN_PREFIX}{token}"
            await self.redis_client.set(key, vpa, ex=ttl)
            return True
        except Exception as e:
            logger.error(f"Failed to set QR txn token: {e}")
            return False

    async def get_qr_txn_token(self, token: str) -> Optional[str]:
        """Get the VPA associated with a verification token."""
        if not self.redis_client:
            return None
        try:
            key = f"{self.QR_TXN_TOKEN_PREFIX}{token}"
            return await self.redis_client.get(key)
        except Exception as e:
            logger.error(f"Failed to get QR txn token: {e}")
            return None

    async def get_charger_connected_at(self, charger_id: str) -> Optional[datetime]:
        """Get connection timestamp for a specific charger"""
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return None
        
        try:
            key = f"{self.connection_key_prefix}{charger_id}"
            connected_at_str = await self.redis_client.get(key)
            
            if not connected_at_str:
                return None
            
            return datetime.fromisoformat(connected_at_str)
        except Exception as e:
            logger.error(f"Failed to get connection data for charger {charger_id}: {e}")
            return None

# Global instance
redis_manager = RedisConnectionManager()