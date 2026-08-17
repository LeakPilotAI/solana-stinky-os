from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"
    log_level: str = "INFO"
    # Backtest thresholds (same spirit as live gates)
    alert_min_score: float = 55.0
    runner_volume_multiple: float = 2.0
    runner_peak_usd: float = 100_000.0


settings = Settings()
