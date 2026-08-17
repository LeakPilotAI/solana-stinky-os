"""Entity resolver configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "entity-resolver"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    # Dedicated group — do NOT share STINKY_CONSUMER_GROUP with event-log
    entity_consumer_group: str = "entity-resolver"

    # Resolution thresholds
    min_co_buy_overlap: int = 3  # wallets that share ≥ N early-buy mints get linked
    deployer_link_confidence: float = 0.85
    co_buy_link_confidence: float = 0.55
    batch_interval_sec: float = 60.0

    # Safe auto-merge (only when BOTH wallets already have entities)
    auto_merge_enabled: bool = True
    auto_merge_min_shared: int = 8  # require strong co-buy evidence
    auto_merge_min_confidence: float = 0.85



settings = Settings()
