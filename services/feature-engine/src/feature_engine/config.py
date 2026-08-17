"""Configuration for the Feature Engine."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STINKY_", env_file=".env")

    service_name: str = "feature-engine"
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    consumer_group: str = "feature-engine"
    consumer_name: str = "feature-engine-1"

    # Feature set version (bump when definitions change)
    feature_def_version: str = "1.0.0"
    feature_set_hash: str = "fs-v1.0.0-launch-basic"

    log_level: str = "INFO"


settings = Settings()
