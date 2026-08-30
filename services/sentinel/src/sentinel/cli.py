"""CLI entrypoint for Stinky Sentinel."""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog

from sentinel.config import settings
from sentinel.history import WalletHistory
from sentinel.migration_watcher import MigrationWatcher
from sentinel.publisher import LaunchPublisher
from sentinel.rpc import SolanaRPC
from sentinel.volume import VolumeMonitor
from sentinel.watcher import PumpFunWatcher
from sentinel.discovery import HighVolumeDiscovery


def _configure_logging() -> None:
    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)
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


def _modes() -> set[str]:
    raw = (settings.watch_modes or "migration").strip().lower()
    if raw in ("both", "all"):
        return {"create", "migration"}
    if raw in ("migration", "migrate", "graduations"):
        return {"migration"}
    if raw in ("create", "launch", "launches"):
        return {"create"}
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return parts or {"migration"}


async def _run() -> None:
    _configure_logging()
    log = structlog.get_logger()
    modes = _modes()
    log.info(
        "sentinel.starting",
        service=settings.service_name,
        rpc=settings.solana_rpc_url.split("?")[0],
        redis=settings.redis_url,
        event_log=settings.event_log_url,
        modes=sorted(modes),
        volume_threshold_usd=settings.volume_threshold_usd,
        rate_limit_cooldown_sec=settings.rate_limit_cooldown_sec,
        helius_key_set=bool(settings.helius_api_key),
        harden="helius-429-v2",
        discovery="high-volume-v1",
    )

    rpc = SolanaRPC()
    health = await rpc.get_health()
    log.info("rpc.health", status=health)

    publisher = LaunchPublisher()
    await publisher.connect()

    volume = VolumeMonitor(publisher)
    await volume.start()
    history = WalletHistory(rpc)
    discovery = HighVolumeDiscovery(volume, interval_sec=45.0)

    tasks: list = []
    create_watcher = None
    migration_watcher = None

    if "create" in modes:
        create_watcher = PumpFunWatcher(publisher=publisher, rpc=rpc, history=history)
        tasks.append(create_watcher.run())
    if "migration" in modes:
        migration_watcher = MigrationWatcher(
            publisher=publisher, volume_monitor=volume, rpc=rpc
        )
        tasks.append(migration_watcher.run())

    # Always run discovery so missed migrations still fill snapshots / gates
    tasks.append(discovery.run())

    if not tasks:
        log.error("sentinel.no_modes", hint="Set STINKY_WATCH_MODES=migration|create|both")
        return

    try:
        await asyncio.gather(*tasks)
    finally:
        discovery.stop()
        if create_watcher:
            create_watcher.stop()
        if migration_watcher:
            migration_watcher.stop()
        await discovery.close()
        await volume.close()
        await publisher.close()
        await history.close()
        await rpc.close()
        log.info("sentinel.stopped")


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
