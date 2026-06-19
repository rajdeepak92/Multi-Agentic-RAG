"""Async SQLAlchemy session factory."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def normalize_async_dsn(dsn: str) -> str:
    """Normalize common PostgreSQL DSN variants to SQLAlchemy asyncpg.

    Args:
        dsn: PostgreSQL connection string from configuration.

    Returns:
        DSN using the ``postgresql+asyncpg://`` driver prefix when a common
        synchronous PostgreSQL prefix was supplied.
    """

    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
    return dsn


def create_async_session_factory(dsn: str) -> Callable[[], AsyncSession]:
    """Create an async session factory.

    Args:
        dsn: PostgreSQL connection string accepted by SQLAlchemy.

    Returns:
        Callable async session factory with ``expire_on_commit`` disabled.
    """

    engine = create_async_engine(normalize_async_dsn(dsn), pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)
