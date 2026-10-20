"""Spec 13 T-SQ-6: migration 0004 keeps the upload's request id on its job."""

from __future__ import annotations

import pytest
from pg import migrate
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def _job_columns(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda c: {col["name"] for col in sa_inspect(c).get_columns("jobs")}
        )


async def test_T_SQ_6_request_id_column_round_trips(database_url: str, engine: AsyncEngine) -> None:
    assert "request_id" in await _job_columns(engine)
    migrate(database_url)  # every boot migrates: a second run changes nothing
    migrate(database_url, "0003", down=True)
    assert "request_id" not in await _job_columns(engine)
    migrate(database_url)
    assert "request_id" in await _job_columns(engine)
