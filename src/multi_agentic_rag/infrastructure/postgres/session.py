"""Async SQLAlchemy session factory."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
        return _normalize_asyncpg_query(dsn)
    if dsn.startswith("postgresql://"):
        return _normalize_asyncpg_query(dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    if dsn.startswith("postgres://"):
        return _normalize_asyncpg_query(dsn.replace("postgres://", "postgresql+asyncpg://", 1))
    return dsn


def create_async_session_factory(
    dsn: str,
    *,
    connect_timeout: float | None = None,
    command_timeout: float | None = None,
    statement_timeout_ms: int | None = None,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_recycle: int = 1800,
    pool_pre_ping: bool = True,
) -> Callable[[], AsyncSession]:
    """Create an async session factory.

    Args:
        dsn: PostgreSQL connection string accepted by SQLAlchemy.
        connect_timeout: Connection establishment timeout in seconds.
        command_timeout: Asyncpg command timeout in seconds.
        statement_timeout_ms: PostgreSQL statement timeout in milliseconds.
        pool_size: SQLAlchemy pool size.
        max_overflow: SQLAlchemy max overflow connections.
        pool_recycle: Pool recycle age in seconds.
        pool_pre_ping: Whether SQLAlchemy validates pooled connections.

    Returns:
        Callable async session factory with ``expire_on_commit`` disabled.
    """

    connect_args: dict[str, object] = {}
    if connect_timeout is not None:
        connect_args["timeout"] = connect_timeout
    if command_timeout is not None:
        connect_args["command_timeout"] = command_timeout
    if statement_timeout_ms is not None:
        connect_args["server_settings"] = {"statement_timeout": str(statement_timeout_ms)}
    engine = create_async_engine(
        normalize_async_dsn(dsn),
        pool_pre_ping=pool_pre_ping,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        connect_args=connect_args,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def _normalize_asyncpg_query(dsn: str) -> str:
    parts = urlsplit(dsn)
    query_pairs = parse_qsl(parts.query, keep_blank_values=True)
    if not query_pairs:
        return dsn
    normalized_pairs = [
        ("ssl", value) if key == "sslmode" else (key, value)
        for key, value in query_pairs
    ]
    return urlunsplit(parts._replace(query=urlencode(normalized_pairs)))
