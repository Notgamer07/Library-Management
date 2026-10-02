import asyncpg
import logging
from typing import Optional, List, Dict, Any
from backend.config import settings

logger = logging.getLogger("library.db")

class DatabasePool:
    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        min_size: int = 10,
        max_size: int = 50,
    ):
        self.name = name
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.min_size = min_size
        self.max_size = max_size
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Initialize asyncpg connection pool."""
        if not self.pool:
            try:
                self.pool = await asyncpg.create_pool(
                    user=self.user,
                    password=self.password,
                    database=self.database,
                    host=self.host,
                    port=self.port,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    command_timeout=10.0,
                    timeout=30.0,
                    max_inactive_connection_lifetime=300.0,
                )
                logger.info(
                    f"[{self.name}] Database pool established "
                    f"({self.min_size}-{self.max_size} connections) at {self.host}:{self.port}/{self.database}"
                )
            except Exception as e:
                logger.error(f"[{self.name}] Failed to connect to PostgreSQL database ({self.host}:{self.port}/{self.database}): {e}")
                raise e

    async def disconnect(self):
        """Close connection pool gracefully."""
        if self.pool:
            await self.pool.close()
            logger.info(f"[{self.name}] Database connection pool closed.")

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

# 1. Dedicated Pool for Bronze Database (Raw Ingestion / Writes)
bronze_db = DatabasePool(
    name="Bronze-DB",
    host=settings.BRONZE_DB_HOST,
    port=settings.BRONZE_DB_PORT,
    user=settings.BRONZE_DB_USER,
    password=settings.BRONZE_DB_PASSWORD,
    database=settings.BRONZE_DB_NAME,
    min_size=settings.DB_POOL_MIN_SIZE,
    max_size=settings.DB_POOL_MAX_SIZE,
)

# Backwards compatibility alias for landing_db
landing_db = bronze_db

# 2. Dedicated Pool for Silver Database (Reads / 3NF OLTP Core)
silver_db = DatabasePool(
    name="Silver-DB",
    host=settings.SILVER_DB_HOST,
    port=settings.SILVER_DB_PORT,
    user=settings.SILVER_DB_USER,
    password=settings.SILVER_DB_PASSWORD,
    database=settings.SILVER_DB_NAME,
    min_size=settings.DB_POOL_MIN_SIZE,
    max_size=settings.DB_POOL_MAX_SIZE,
)

# 3. Dedicated Pool for Gold Database (Analytical Aggregations & KPIs)
gold_db = DatabasePool(
    name="Gold-DB",
    host=settings.GOLD_DB_HOST,
    port=settings.GOLD_DB_PORT,
    user=settings.GOLD_DB_USER,
    password=settings.GOLD_DB_PASSWORD,
    database=settings.GOLD_DB_NAME,
    min_size=5,
    max_size=25,
)

class MultiDatabaseManager:
    """Manages multi-instance connection lifecycle and provides routing."""
    def __init__(self, bronze: DatabasePool, silver: DatabasePool, gold: DatabasePool):
        self.bronze = bronze
        self.silver = silver
        self.gold = gold

    async def connect(self):
        await self.bronze.connect()
        await self.silver.connect()
        await self.gold.connect()

    async def disconnect(self):
        await self.gold.disconnect()
        await self.silver.disconnect()
        await self.bronze.disconnect()

    @property
    def landing(self) -> DatabasePool:
        return self.bronze

    @property
    def pool(self) -> Optional[asyncpg.Pool]:
        # Defaults to silver OLTP pool for backwards compatibility
        return self.silver.pool

    async def fetch_all(self, query: str, *args) -> List[Dict[str, Any]]:
        return await self.silver.fetch_all(query, *args)

    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        return await self.silver.fetch_one(query, *args)

    async def execute(self, query: str, *args) -> str:
        return await self.silver.execute(query, *args)

db = MultiDatabaseManager(bronze=bronze_db, silver=silver_db, gold=gold_db)
