"""Blobs in Postgres (BLOB_STORE=postgres) and the blob budget the sweeper enforces."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.repositories import documents
from inkthread.services.retention import RetentionSweeper
from inkthread.storage.pgblobs import PgBlobStore

pytestmark = pytest.mark.integration


async def test_round_trip_and_prefix_delete(sessions: async_sessionmaker[AsyncSession]) -> None:
    store = PgBlobStore(sessions)
    await store.put("pages/abc/1.png", b"one", "image/png")
    await store.put("pages/abc/1.png", b"uno", "image/png")  # overwrite
    await store.put("pages/abc/2.png", b"two", "image/png")
    await store.put("pages/abd/1.png", b"keep", "image/png")
    assert await store.get("pages/abc/1.png") == b"uno"
    assert await store.get("nope") is None
    await store.delete_prefix("pages/abc/")
    assert await store.get("pages/abc/2.png") is None
    assert await store.get("pages/abd/1.png") == b"keep"
    with pytest.raises(ValueError, match="key"):
        await store.put("../x", b"", "text/plain")


async def test_budget_evicts_oldest_uploads_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    store = PgBlobStore(sessions)
    now = dt.datetime.now(dt.UTC)
    later = now + dt.timedelta(days=7)
    async with sessions() as s:
        old = await documents.create(
            s,
            sha256="1" * 64,
            file_name=None,
            page_count=1,
            byte_size=1,
            kind="upload",
            expires_at=later,
        )
        new = await documents.create(
            s,
            sha256="2" * 64,
            file_name=None,
            page_count=1,
            byte_size=1,
            kind="upload",
            expires_at=later,
        )
        sample = await documents.create(
            s,
            sha256="3" * 64,
            file_name=None,
            page_count=1,
            byte_size=1,
            kind="sample",
            expires_at=None,
        )
        await s.commit()
    for sha in ("1" * 64, "2" * 64, "3" * 64):
        await store.put(f"pdf/{sha}.pdf", b"x" * 600, "application/pdf")
    sweeper = RetentionSweeper(sessions, store, blob_budget_bytes=1300, usage=store.total_bytes)
    assert await sweeper.sweep(now) == 1
    async with sessions() as s:
        assert await documents.get(s, old.id) is None
        assert await documents.get(s, new.id) is not None
        assert await documents.get(s, sample.id) is not None
    assert await store.get(f"pdf/{'3' * 64}.pdf") is not None
