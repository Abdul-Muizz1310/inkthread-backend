"""Alembic environment: async, URL from DATABASE_URL (normalised like the app's engine)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection

from inkthread.core.db import make_engine
from inkthread.models import Base

target_metadata = Base.metadata


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        msg = "DATABASE_URL is required to run migrations"
        raise RuntimeError(msg)
    engine = make_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


asyncio.run(_run())
