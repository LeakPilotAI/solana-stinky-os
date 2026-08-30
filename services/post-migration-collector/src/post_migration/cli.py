"""CLI entrypoint for Post-Migration Intelligence Collector.

Usage:
  stinky-collector                  # consume Redis forever
  stinky-collector backfill         # track migrations with 0 buyers
  stinky-collector track <mint>     # force-track one mint (optional --pool)
  stinky-collector recompute-performance  # rebuild wallet_performance from trades
  stinky-collector learn-success    # label token outcomes + credit early buyers
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import structlog

from post_migration.config import settings
from post_migration.service import CollectorService
from post_migration.store import Store


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


async def _run_forever() -> None:
    service = CollectorService()
    await service.run_forever()


async def _run_backfill(limit: int) -> None:
    service = CollectorService()
    await service.start()
    try:
        n = await service.backfill_from_events(limit=limit)
        log = structlog.get_logger()
        log.info("collector.backfill_spawned", tracks=n)
        await asyncio.sleep(min(settings.early_buyer_window_sec, 180.0))
        log.info("collector.backfill_wait_done", metrics=service.health)
    finally:
        await service.stop()


async def _run_track(mint: str, pool: str | None) -> None:
    service = CollectorService()
    await service.start()
    try:
        ok = await service.track_mint(mint, pool=pool)
        log = structlog.get_logger()
        log.info("collector.manual_track", mint=mint, started=ok)
        await asyncio.sleep(min(settings.early_buyer_window_sec, 300.0))
        log.info("collector.manual_track_done", metrics=service.health)
    finally:
        await service.stop()


async def _run_recompute(limit: int) -> None:
    store = Store()
    log = structlog.get_logger()
    try:
        await store.ensure_schema()
        n = await store.recompute_all_performance(limit=limit)
        log.info("collector.recompute_performance_done", wallets=n)
    finally:
        await store.close()


async def _run_learn(token_limit: int) -> None:
    from post_migration.learn import SuccessLearner

    log = structlog.get_logger()
    log.info("collector.learn_success_start", token_limit=token_limit)
    learner = SuccessLearner()
    try:
        result = await learner.run_full(token_limit=token_limit)
        log.info("collector.learn_success_done", **result)
    finally:
        await learner.close()


def main() -> None:
    _configure_logging()
    parser = argparse.ArgumentParser(prog="stinky-collector")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="Consume Redis stream forever (default)")

    p_bf = sub.add_parser("backfill", help="Track recent migrations with 0 buyers")
    p_bf.add_argument("--limit", type=int, default=10)

    p_tr = sub.add_parser("track", help="Force-track one mint")
    p_tr.add_argument("mint")
    p_tr.add_argument("--pool", default=None)

    p_rc = sub.add_parser(
        "recompute-performance",
        help="Rebuild wallet_performance from wallet_trades (replay)",
    )
    p_rc.add_argument("--limit", type=int, default=5000)

    p_ln = sub.add_parser(
        "learn-success",
        help="Label token outcomes from snapshots + credit early buyers who caught runners",
    )
    p_ln.add_argument("--token-limit", type=int, default=2000)

    args = parser.parse_args()
    cmd = args.cmd or "run"

    log = structlog.get_logger()
    log.info(
        "collector.booting",
        cmd=cmd,
        max_early_buyers=settings.max_early_buyers,
        redis=settings.redis_url,
        enable_helius=bool(getattr(settings, "enable_helius", False)),
        trade_source="pump.v2",
        service=settings.service_name if hasattr(settings, "service_name") else "post-migration-collector",
        track_max_duration_sec=getattr(settings, "track_max_duration_sec", 3600),
    )

    if cmd == "backfill":
        asyncio.run(_run_backfill(args.limit))
    elif cmd == "track":
        asyncio.run(_run_track(args.mint, args.pool))
    elif cmd == "recompute-performance":
        asyncio.run(_run_recompute(args.limit))
    elif cmd == "learn-success":
        asyncio.run(_run_learn(args.token_limit))
    else:
        asyncio.run(_run_forever())


if __name__ == "__main__":
    main()
