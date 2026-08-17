"""Configuration for the Event Log service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Shared monorepo .env has keys for sentinel/collector/api/web.
    # Event-log must IGNORE unknowns or it crashes on startup (Events red).
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "event-log"
    environment: str = "development"

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"

    # Redis / transport
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    consumer_group: str = "event-log"

    # Object storage (MinIO / S3)
    object_storage_endpoint: str = "http://localhost:9010"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    object_storage_bucket: str = "stinky"

    # Observability
    log_level: str = "INFO"
    metrics_port: int = 9101

    # Quality
    max_payload_bytes: int = 1_048_576  # 1 MiB


settings = Settings()
