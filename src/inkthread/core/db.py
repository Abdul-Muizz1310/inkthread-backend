"""The async engine: Neon-aware URL normalisation, pre-ping and recycle (spec 08 § 1)."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def normalise_url(url: str) -> str:
    """`postgres://` → `postgresql+asyncpg://`; `sslmode` → `ssl`; drop `channel_binding`."""
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
        scheme = "postgresql+asyncpg"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "channel_binding":
            continue
        query.append(("ssl", value) if key == "sslmode" else (key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def make_engine(url: str, **kwargs: Any) -> AsyncEngine:  # noqa: ANN401 - engine options
    """An engine that survives Neon's idle suspends and PgBouncer pooling."""
    norm = normalise_url(url)
    connect_args: dict[str, object] = {}
    if "-pooler" in (urlsplit(norm).hostname or ""):
        connect_args["statement_cache_size"] = 0  # PgBouncer breaks prepared statements
    return create_async_engine(
        norm, pool_pre_ping=True, pool_recycle=300, connect_args=connect_args, **kwargs
    )


def make_sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Short-lived sessions; objects stay readable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
