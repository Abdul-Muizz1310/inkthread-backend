"""Postgres for integration tests: one Testcontainers server per session, one database per test.

Migrations run through Alembic in a subprocess, exactly as the container entrypoint runs them.
Tests skip with a reason when Docker is not available.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from pg import migrate
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from inkthread.core.db import make_engine


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:  # noqa: BLE001 - any failure means "no docker"
        return False
    return True


@pytest.fixture(scope="session")
def pg_server() -> Iterator[str]:
    """A Postgres server URL (without a database name)."""
    if not _docker_available():
        pytest.skip("Docker is not available for the Postgres tier")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        yield url.rsplit("/", 1)[0]


@pytest.fixture
async def database_url(pg_server: str) -> AsyncIterator[str]:
    """A fresh, migrated database for one test."""
    name = "t_" + uuid.uuid4().hex[:12]
    admin = make_engine(f"{pg_server}/postgres", isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    url = f"{pg_server}/{name}"
    migrate(url)
    try:
        yield url
    finally:
        async with admin.connect() as conn:
            await conn.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.dispose()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
