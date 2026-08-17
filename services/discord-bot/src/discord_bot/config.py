"""Discord bot configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STINKY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "discord-bot"
    environment: str = "development"
    log_level: str = "INFO"

    discord_token: str | None = None
    discord_guild_id: int | None = None
    discord_alert_channel_id: int | None = None

    database_url: str = "postgresql+asyncpg://stinky:stinky@localhost:5433/stinky"
    redis_url: str = "redis://localhost:6380/0"
    event_stream: str = "stinky.events"
    discord_consumer_group: str = "discord-bot"

    volume_threshold_usd: float = 25_000.0
    alert_min_score: float = 55.0
    alert_min_meaningful_buyers: int = 3

    dexscreener_token_url: str = "https://api.dexscreener.com/latest/dex/tokens/{mint}"

    allowed_dex_ids: str = "pumpswap,pumpfun,pump"
    denied_dex_ids: str = "meteora,raydium,orca,phoenix,lifinity,saber,aldrin,fluxbeam,pumpamm"
    require_pump_mint_suffix: bool = True
    # HARD GATE fail-closed — must match FilterEngine / qualify default
    # Missing or unverified fees → NO Discord message.
    min_fees_sol: float = 5.0


settings = Settings()
