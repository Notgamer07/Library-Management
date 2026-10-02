import os
from pathlib import Path
from pydantic_settings import BaseSettings

# Automatically load .env file if present
env_file = Path(__file__).resolve().parent.parent / '.env'
if env_file.exists():
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

class Settings(BaseSettings):
    PROJECT_NAME: str = "High-Throughput Medallion Library Management System"
    API_V1_STR: str = "/api/v1"
    
    # 1. Bronze Database Configuration (Raw Ingestion Layer)
    BRONZE_DB_HOST: str = os.getenv("BRONZE_DB_HOST")
    BRONZE_DB_PORT: int = int(os.getenv("BRONZE_DB_PORT"))
    BRONZE_DB_USER: str = os.getenv("BRONZE_DB_USER")
    BRONZE_DB_PASSWORD: str = os.getenv("BRONZE_DB_PASSWORD")
    BRONZE_DB_NAME: str = os.getenv("BRONZE_DB_NAME")

    # 2. Silver Database Configuration (3NF Clean Relational OLTP Core)
    SILVER_DB_HOST: str = os.getenv("SILVER_DB_HOST", os.getenv("POSTGRES_HOST"))
    SILVER_DB_PORT: int = int(os.getenv("SILVER_DB_PORT", os.getenv("POSTGRES_PORT")))
    SILVER_DB_USER: str = os.getenv("SILVER_DB_USER", os.getenv("POSTGRES_USER"))
    SILVER_DB_PASSWORD: str = os.getenv("SILVER_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD"))
    SILVER_DB_NAME: str = os.getenv("SILVER_DB_NAME", os.getenv("POSTGRES_DB"))

    # 3. Gold Database Configuration (Dedicated Day-Wise & Month-Wise Analytics)
    GOLD_DB_HOST: str = os.getenv("GOLD_DB_HOST")
    GOLD_DB_PORT: int = int(os.getenv("GOLD_DB_PORT"))
    GOLD_DB_USER: str = os.getenv("GOLD_DB_USER")
    GOLD_DB_PASSWORD: str = os.getenv("GOLD_DB_PASSWORD")
    GOLD_DB_NAME: str = os.getenv("GOLD_DB_NAME")

    # Pipeline Daemon Settings
    PIPELINE_BATCH_SIZE: int = int(os.getenv("PIPELINE_BATCH_SIZE", "10000"))
    PIPELINE_INTERVAL_SECONDS: int = int(os.getenv("PIPELINE_INTERVAL_SECONDS", "90"))

    # Backwards-compatibility aliases for Landing layer -> redirected to Bronze
    @property
    def LANDING_DB_HOST(self) -> str:
        return self.BRONZE_DB_HOST

    @property
    def LANDING_DB_PORT(self) -> int:
        return self.BRONZE_DB_PORT

    @property
    def LANDING_DB_USER(self) -> str:
        return self.BRONZE_DB_USER

    @property
    def LANDING_DB_PASSWORD(self) -> str:
        return self.BRONZE_DB_PASSWORD

    @property
    def LANDING_DB_NAME(self) -> str:
        return self.BRONZE_DB_NAME

    # Backwards-compatibility aliases for POSTGRES_* -> Silver
    @property
    def POSTGRES_HOST(self) -> str:
        return self.SILVER_DB_HOST

    @property
    def POSTGRES_PORT(self) -> int:
        return self.SILVER_DB_PORT

    @property
    def POSTGRES_USER(self) -> str:
        return self.SILVER_DB_USER

    @property
    def POSTGRES_PASSWORD(self) -> str:
        return self.SILVER_DB_PASSWORD

    @property
    def POSTGRES_DB(self) -> str:
        return self.SILVER_DB_NAME

    # Connection Pool Settings for ~1000 req/sec Target
    DB_POOL_MIN_SIZE: int = int(os.getenv("DB_POOL_MIN_SIZE", "20"))
    DB_POOL_MAX_SIZE: int = int(os.getenv("DB_POOL_MAX_SIZE", "100"))
    
    # Redis Configuration
    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: str = os.getenv("REDIS_PASSWORD", "")
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "60"))
    
    @property
    def BRONZE_DATABASE_URL(self) -> str:
        return f"postgresql://{self.BRONZE_DB_USER}:{self.BRONZE_DB_PASSWORD}@{self.BRONZE_DB_HOST}:{self.BRONZE_DB_PORT}/{self.BRONZE_DB_NAME}"

    @property
    def SILVER_DATABASE_URL(self) -> str:
        return f"postgresql://{self.SILVER_DB_USER}:{self.SILVER_DB_PASSWORD}@{self.SILVER_DB_HOST}:{self.SILVER_DB_PORT}/{self.SILVER_DB_NAME}"

    @property
    def GOLD_DATABASE_URL(self) -> str:
        return f"postgresql://{self.GOLD_DB_USER}:{self.GOLD_DB_PASSWORD}@{self.GOLD_DB_HOST}:{self.GOLD_DB_PORT}/{self.GOLD_DB_NAME}"

    @property
    def LANDING_DATABASE_URL(self) -> str:
        return self.BRONZE_DATABASE_URL

    @property
    def DATABASE_URL(self) -> str:
        return self.SILVER_DATABASE_URL

settings = Settings()
