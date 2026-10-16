"""Blobs in Postgres (BLOB_STORE=postgres), where production keeps the samples' files."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
