"""Sentinel configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "sentinel"
    environment: str = "development"
    log_level: str = "INFO"

    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    solana_ws_url: str = "wss://api.mainnet-beta.solana.com"
    helius_api_key: str | None = None

    public_rpc_url: str = "https://api.mainnet-beta.solana.com"
    public_ws_url: str = "wss://api.mainnet-beta.solana.com"
    use_public_health_check: bool = True

    pump_fun_program: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    token_program: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"

    commitment: str = "confirmed"
    reconnect_delay_sec: float = 5.0
    max_reconnect_delay_sec: float = 120.0

    rate_limit_cooldown_sec: float = 300.0
    rate_limit_max_cooldown_sec: float = 900.0
    skip_rpc_history_when_throttled: bool = True
    skip_rpc_rescue_when_throttled: bool = True
    migration_watcher_start_delay_sec: float = 3.0
    prefer_public_ws: bool = False
    public_ws_fallback_on_429: bool = True

    watch_modes: str = "migration"

    event_log_url: str | None = "http://localhost:8002"

    # Early migration observation threshold (not the opportunity screen)
    volume_threshold_usd: float = 25_000.0
    volume_poll_interval_sec: float = 20.0
    volume_max_watch_sec: float = 900.0

    allowed_dex_ids: str = "pumpswap,pumpfun,pump"
    denied_dex_ids: str = "meteora,raydium,orca,phoenix,lifinity,saber,aldrin,fluxbeam,pumpamm"
    require_pump_mint_suffix: bool = True
    # Hard ops floor: 1.0 SOL. Override via STINKY_MIN_FEES_SOL.
    # HARD GATE: missing / unverified / below floor ? REJECT.
    min_fees_sol: float = 1.0
    birdeye_api_key: str | None = None

    # Full opportunity screen (FilterEngine) ? separate from early volume watch
    filter_version: str = "axiom-parity-v1.0.0"
    min_liquidity_usd: float = 8.0
    min_volume_usd: float = 100_000.0
    min_market_cap_usd: float = 31_333.0
    require_at_least_one_social: bool = True


settings = Settings()
