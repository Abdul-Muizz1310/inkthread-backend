"""Blobs stored in Postgres."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.models import BlobRow


async def put(s: AsyncSession, key: str, data: bytes, content_type: str) -> None:
    """Insert or replace one blob."""
    stmt = insert(BlobRow).values(key=key, content_type=content_type, data=data, size=len(data))
    stmt = stmt.on_conflict_do_update(
        index_elements=[BlobRow.key],
        set_={
            "content_type": stmt.excluded.content_type,
            "data": stmt.excluded.data,
            "size": stmt.excluded.size,
        },
    )
    await s.execute(stmt)


async def get(s: AsyncSession, key: str) -> bytes | None:
    """One blob's bytes."""
    return (await s.execute(select(BlobRow.data).where(BlobRow.key == key))).scalar_one_or_none()


async def delete_prefix(s: AsyncSession, prefix: str) -> None:
    """Delete every blob whose key starts with `prefix` (LIKE wildcards escaped)."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    await s.execute(delete(BlobRow).where(BlobRow.key.like(escaped + "%", escape="\\")))
