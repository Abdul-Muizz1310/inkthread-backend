"""Documents: create, find by content, status, samples, retention."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.models import Document

Doc = Document


async def create(
    s: AsyncSession,
    *,
    sha256: str,
    file_name: str | None,
    page_count: int,
    byte_size: int,
    kind: str,
    expires_at: dt.datetime | None,
) -> Document:
    """Insert a queued document."""
    doc = Document(
        sha256=sha256,
        file_name=file_name,
        page_count=page_count,
        byte_size=byte_size,
        kind=kind,
        status="queued",
        expires_at=expires_at,
    )
    s.add(doc)
    await s.flush()
    return doc


async def get(s: AsyncSession, document_id: uuid.UUID) -> Document | None:
    """By id."""
    return await s.get(Document, document_id)


async def get_by_sha(s: AsyncSession, sha256: str) -> Document | None:
    """By content hash."""
    return (await s.execute(select(Document).where(Document.sha256 == sha256))).scalar_one_or_none()


async def get_by_sha_for_update(s: AsyncSession, sha256: str) -> Document | None:
    """By content hash, locking the row until the transaction ends."""
    q = select(Document).where(Document.sha256 == sha256).with_for_update()
    return (await s.execute(q)).scalar_one_or_none()


async def set_status(
    s: AsyncSession, document_id: uuid.UUID, status: str, *, title: str | None = None
) -> None:
    """Move a document's status, and set its title when known."""
    doc = await s.get(Document, document_id)
    if doc is None:
        return
    doc.status = status
    if title is not None:
        doc.title = title
    await s.flush()


async def list_samples(s: AsyncSession) -> list[Document]:
    """Samples, oldest first."""
    rows = await s.execute(
        select(Document).where(Document.kind == "sample").order_by(Document.created_at)
    )
    return list(rows.scalars())


async def expired_uploads(s: AsyncSession, now: dt.datetime) -> list[Document]:
    """Uploads past their expiry."""
    rows = await s.execute(
        select(Document).where(
            Document.kind == "upload",
            Document.expires_at.is_not(None),
            Document.expires_at < now,
        )
    )
    return list(rows.scalars())


async def uploads_oldest_first(s: AsyncSession) -> list[Document]:
    """Uploads (never samples), oldest first: the blob budget's eviction order."""
    rows = await s.execute(
        select(Document).where(Document.kind == "upload").order_by(Document.created_at, Document.id)
    )
    return list(rows.scalars())


async def delete(s: AsyncSession, document_id: uuid.UUID) -> None:
    """Delete a document; its jobs, events and graph cascade."""
    await s.execute(sa_delete(Document).where(Document.id == document_id))
