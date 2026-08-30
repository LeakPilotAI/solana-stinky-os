"""Post-migration collector configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "post-migration-collector"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    # Dedicated name so STINKY_CONSUMER_GROUP in .env does not override
    collector_consumer_group: str = "post-migration-collector"
    event_log_url: str | None = "http://localhost:8002"

    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    helius_api_key: str | None = None
    # Helius is OPTIONAL. Default off so a maxed key cannot stall the OS.
    enable_helius: bool = False
    commitment: str = "confirmed"

    max_early_buyers: int = 20
    min_meaningful_sol: float = 0.01
    track_poll_interval_sec: float = 20.0
    track_max_duration_sec: float = 3600.0
    early_buyer_window_sec: float = 900.0
    market_snapshot_interval_sec: float = 60.0
    max_concurrent_tracks: int = 50
    buyer_exclude_addresses: str = ""

    # Free pump.fun swap-api v2 pages per poll (100 trades/page).
    pump_trade_pages: int = 2
    pump_trade_limit: int = 100
    rpc_sig_limit: int = 30

    milestone_multiples: str = "2,5,10,50,100"
    health_port: int = 9102


settings = Settings()
