"""Async SQLAlchemy session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
import time

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stinky_api.config import settings

logger = structlog.get_logger(__name__)

SLOW_SQL_THRESHOLD_MS = 500.0
SLOW_SQL_TEXT_LIMIT = 600


def _compact_sql(statement: str) -> str:
    """Compact SQL for bounded diagnostic logs without changing execution."""
    return " ".join(str(statement).split())[:SLOW_SQL_TEXT_LIMIT]


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
    pool_timeout=5,
    pool_recycle=180,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._genesis_query_started_at = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    started_at = getattr(context, "_genesis_query_started_at", None)
    if started_at is None:
        return
    duration_ms = (time.perf_counter() - started_at) * 1000.0
    if duration_ms < SLOW_SQL_THRESHOLD_MS:
        return

    try:
        checked_out = engine.pool.checkedout()
    except Exception:
        checked_out = None

    logger.warning(
        "api.slow_sql",
        duration_ms=round(duration_ms, 1),
        statement=_compact_sql(statement),
        executemany=bool(executemany),
        pool_checkedout=checked_out,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped transaction and durably commit successful writes.

    Several evidence-only GET surfaces intentionally persist immutable audit
    snapshots. SQLAlchemy sessions do not auto-commit when the context closes,
    so without an explicit successful-request commit those snapshot INSERTs are
    rolled back even when the HTTP response is 200. Read-only requests are
    unaffected by committing an otherwise clean transaction.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
