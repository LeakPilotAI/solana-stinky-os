"""API configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "api"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://stinky:stinky@127.0.0.1:5433/stinky"
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    api_port: int = 8010
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    event_log_url: str = "http://localhost:8002"
    min_fees_sol: float = 4.0
    paper_readiness_min_closed_outcomes: str | None = None
    paper_readiness_min_market_cap_samples: str | None = None
    paper_readiness_min_outcome_classes: str | None = None


settings = Settings()
