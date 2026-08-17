"""stinky-replay CLI."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

import structlog

from stinky_replay.config import settings
from stinky_replay.engine import ReplayEngine


def _log() -> None:
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


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> None:
    _log()
    log = structlog.get_logger()
    p = argparse.ArgumentParser(
        prog="stinky-replay",
        description="Replay event store + backtest alert score gate (measured only)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("events", help="Count events by type in a time window")
    pe.add_argument("--since", type=str, default=None, help="ISO datetime")
    pe.add_argument("--until", type=str, default=None, help="ISO datetime")
    pe.add_argument("--type", dest="event_type", type=str, default=None)

    pb = sub.add_parser("backtest", help="Score-gate precision vs market_snapshots")
    pb.add_argument("--min-score", type=float, default=None)
    pb.add_argument("--limit", type=int, default=500)

    sub.add_parser("funnel", help="Migration → track → buyers → alert funnel")

    args = p.parse_args()
    log.info("replay.booting", cmd=args.cmd)

    async def _run() -> int:
        eng = ReplayEngine()
        try:
            if args.cmd == "events":
                out = await eng.event_counts(
                    since=_parse_dt(args.since),
                    until=_parse_dt(args.until),
                    event_type=args.event_type,
                )
            elif args.cmd == "backtest":
                out = await eng.score_gate_backtest(
                    min_score=args.min_score, limit=args.limit
                )
            elif args.cmd == "funnel":
                out = await eng.migration_funnel()
            else:
                log.error("replay.unknown_cmd", cmd=args.cmd)
                return 2
            print(json.dumps(out, indent=2, default=str))
            return 0
        finally:
            await eng.close()

    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
