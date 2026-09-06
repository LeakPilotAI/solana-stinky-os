"""Async SQLAlchemy session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from stinky_api.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=5,
    pool_timeout=5,
    pool_recycle=180,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
