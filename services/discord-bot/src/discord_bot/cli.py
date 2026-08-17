"""CLI entrypoint for Stinky Discord bot."""

from __future__ import annotations

import logging
import sys

import structlog

from discord_bot.bot import StinkyBot
from discord_bot.config import settings


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    _configure_logging()
    log = structlog.get_logger()
    if not settings.discord_token:
        log.error("discord.token_missing", hint="Set STINKY_DISCORD_TOKEN in .env")
        sys.exit(1)
    log.info(
        "discord.starting",
        volume_threshold_usd=settings.volume_threshold_usd,
        guild_id=settings.discord_guild_id,
        channel_id=settings.discord_alert_channel_id,
    )
    bot = StinkyBot()
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
