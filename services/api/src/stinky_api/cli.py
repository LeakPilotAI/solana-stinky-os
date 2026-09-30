"""CLI entry for stinky-api."""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog
import uvicorn

from stinky_api.config import settings


def _use_windows_selector_loop() -> None:
    """Avoid Proactor connection-reset callback tracebacks in long-lived local HTTP services."""
    if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    _use_windows_selector_loop()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    uvicorn.run(
        "stinky_api.main:app",
        host="127.0.0.1",
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
