import redis.asyncio as redis
import json
import logging
from typing import Optional, Any
from backend.config import settings

logger = logging.getLogger("library.cache")

class CacheManager:
    def __init__(self):
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        """Initialize Redis connection client."""
        try:
            self.client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD or None,
                decode_responses=True
            )
            await self.client.ping()
            logger.info("Redis cache client connected successfully.")
        except Exception as e:
            logger.warning(f"Redis cache connection failed: {e}. Fallback to direct DB mode.")
            self.client = None

    async def disconnect(self):
        """Close Redis client connection."""
        if self.client:
            await self.client.close()

    async def get(self, key: str) -> Optional[Any]:
        """Fetch cached item by key."""
        if not self.client:
            return None
        try:
            data = await self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.warning(f"Redis GET error on key '{key}': {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = settings.CACHE_TTL_SECONDS):
        """Set cache key with TTL expiration."""
        if not self.client:
            return
        try:
            await self.client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as e:
            logger.warning(f"Redis SET error on key '{key}': {e}")

    async def invalidate(self, pattern: str):
        """Invalidate all keys matching pattern."""
        if not self.client:
            return
        try:
            keys = await self.client.keys(pattern)
            if keys:
                await self.client.delete(*keys)
                logger.info(f"Invalidated {len(keys)} cache keys matching '{pattern}'")
        except Exception as e:
            logger.warning(f"Redis INVALIDATE error on pattern '{pattern}': {e}")

cache = CacheManager()
