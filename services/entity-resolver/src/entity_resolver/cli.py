"""CLI for entity resolver."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import structlog

from entity_resolver.config import settings
from entity_resolver.resolver import EntityResolver
from entity_resolver.service import EntityService


def _configure_logging() -> None:
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


async def _run_batch() -> None:
    r = EntityResolver()
    try:
        stats = await r.run_batch()
        structlog.get_logger().info("entity.batch_complete", **stats)
    finally:
        await r.close()


async def _run_merges() -> None:
    r = EntityResolver()
    try:
        # Force thresholds for explicit merge pass
        stats = await r.run_batch()
        multi = await r._store.multi_wallet_entities(limit=20)
        structlog.get_logger().info(
            "entity.merge_pass_done",
            **stats,
            multi_wallet_top=len(multi),
        )
        for m in multi[:10]:
            structlog.get_logger().info(
                "entity.multi_wallet",
                entity_id=m.get("entity_id"),
                wallets=m.get("wallet_count"),
                launches=m.get("launch_count"),
                primary=m.get("primary_wallet"),
            )
    finally:
        await r.close()


async def _show_candidates() -> None:
    r = EntityResolver()
    try:
        cands = await r._store.merge_candidates(
            min_shared=settings.auto_merge_min_shared, limit=30
        )
        structlog.get_logger().info("entity.merge_candidates", count=len(cands))
        for c in cands:
            structlog.get_logger().info("entity.merge_candidate", **c)
    finally:
        await r.close()


def main() -> None:
    _configure_logging()
    log = structlog.get_logger()
    parser = argparse.ArgumentParser(prog="stinky-entities")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="consume events forever (default)")
    sub.add_parser("batch", help="one resolution + safe-merge pass then exit")
    sub.add_parser("merges", help="batch + print multi-wallet entities")
    sub.add_parser("candidates", help="list strong merge candidates without merging")
    args = parser.parse_args()
    cmd = args.cmd or "run"

    log.info(
        "entity_resolver.booting",
        service=settings.service_name,
        cmd=cmd,
        auto_merge=settings.auto_merge_enabled,
        min_shared=settings.auto_merge_min_shared,
    )

    if cmd == "batch":
        asyncio.run(_run_batch())
        return
    if cmd == "merges":
        asyncio.run(_run_merges())
        return
    if cmd == "candidates":
        asyncio.run(_show_candidates())
        return

    service = EntityService()
    try:
        asyncio.run(service.run_forever())
    except KeyboardInterrupt:
        log.info("entity_resolver.shutdown")
        sys.exit(0)


if __name__ == "__main__":
    main()
