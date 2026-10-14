"""A blob store in Postgres, for deployments without object storage (BLOB_STORE=postgres)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.repositories import blobs as repo
from inkthread.storage.blobs import check_key


class PgBlobStore:
    """Blobs as rows of the `blobs` table."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._sessions() as s, s.begin():
            await repo.put(s, check_key(key), data, content_type)

    async def get(self, key: str) -> bytes | None:
        async with self._sessions() as s:
            return await repo.get(s, check_key(key))

    async def delete_prefix(self, prefix: str) -> None:
        async with self._sessions() as s, s.begin():
            await repo.delete_prefix(
                s, check_key(prefix.rstrip("/")) + ("/" if prefix.endswith("/") else "")
            )

    async def total_bytes(self) -> int:
        """Bytes stored, for the blob budget."""
        async with self._sessions() as s:
            return await repo.total_bytes(s)
