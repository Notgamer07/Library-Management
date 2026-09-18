import asyncpg
import logging
from typing import Optional, List, Dict, Any
from backend.config import settings

logger = logging.getLogger("library.db")

class DatabasePool:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Initialize asyncpg connection pool with high concurrency limits.
        
        With 4 Uvicorn workers each having their own pool (max_size=100), the
        system can sustain ~400 concurrent DB operations, well above the
        1000 req/sec target (most requests are sub-10ms).
        """
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(
                    user=settings.POSTGRES_USER,
                    password=settings.POSTGRES_PASSWORD,
                    database=settings.POSTGRES_DB,
                    host=settings.POSTGRES_HOST,
                    port=settings.POSTGRES_PORT,
                    min_size=settings.DB_POOL_MIN_SIZE,
                    max_size=settings.DB_POOL_MAX_SIZE,
                    # Prevent slow queries from tying up pool connections
                    command_timeout=10.0,
                    # How long to wait for a free connection before raising
                    timeout=30.0,
                    # Keep connections alive under load
                    max_inactive_connection_lifetime=300.0,
                )
                logger.info(
                    f"Database pool established "
                    f"({settings.DB_POOL_MIN_SIZE}-{settings.DB_POOL_MAX_SIZE} connections)"
                )
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL database: {e}")
                raise e

    async def disconnect(self):
        """Close connection pool gracefully."""
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed.")

    async def fetch_all(self, query: str, *args) -> List[Dict[str, Any]]:
        """Execute SELECT query returning list of dicts."""
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, *args)
            return [dict(record) for record in records]

    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """Execute SELECT query returning a single record."""
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, *args)
            return dict(record) if record else None

    async def execute(self, query: str, *args) -> str:
        """Execute DML statement (INSERT/UPDATE/DELETE)."""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)

db = DatabasePool()
