"""CLI entry for the Event Log service."""

from __future__ import annotations

import asyncio
import sys

import uvicorn

from event_log.config import settings


def _use_windows_selector_loop() -> None:
    """Avoid Proactor connection-reset callback tracebacks in long-lived local HTTP services."""
    if sys.platform == "win32" and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def main() -> None:
    _use_windows_selector_loop()
    uvicorn.run(
        "event_log.api:app",
        host="127.0.0.1",
        port=settings.event_log_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
