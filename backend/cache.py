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
        """Initialize Redis connection client with automatic host fallback."""
        candidates = [settings.REDIS_HOST]
        for fallback in ("127.0.0.1", "localhost"):
            if fallback not in candidates:
                candidates.append(fallback)

        for host in candidates:
            try:
                client = redis.Redis(
                    host=host,
                    port=settings.REDIS_PORT,
                    password=settings.REDIS_PASSWORD or None,
                    decode_responses=True,
                    socket_connect_timeout=1.0
                )
                await client.ping()
                self.client = client
                logger.info(f"Redis cache client connected successfully to {host}:{settings.REDIS_PORT}.")
                return
            except Exception as e:
                logger.debug(f"Redis connection attempt to {host} failed: {e}")

        logger.warning("Redis cache connection failed on all candidate hosts. Fallback to direct DB mode.")
        self.client = None

    async def disconnect(self):
        """Close Redis client connection."""
        if self.client:
            if hasattr(self.client, "aclose"):
                await self.client.aclose()
            else:
                await self.client.close()

    async def get_raw(self, key: str) -> Optional[str]:
        """Fetch cached item as raw JSON string without deserialization overhead."""
        if not self.client:
            return None
        try:
            return await self.client.get(key)
        except Exception as e:
            logger.warning(f"Redis GET error on key '{key}': {e}")
            return None

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
