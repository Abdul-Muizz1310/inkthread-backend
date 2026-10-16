"""Upload use case (spec 07 § 2, spec 08 § 2, § 4): validate, hash, dedupe, hold, enqueue."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core.errors import (
    EmptyFile,
    NotAPdf,
    PdfEncrypted,
    PdfUnreadable,
    QueueFull,
    TooManyPages,
)
from inkthread.reader import inspect as pdf_inspect
from inkthread.repositories import documents, jobs
from inkthread.schemas.documents import DocumentKind, UploadOut
from inkthread.services.views import document_out, job_out
from inkthread.storage.stores import Stores

PDF_MARKER = b"%PDF-"
MARKER_WINDOW = 1024


@dataclass(frozen=True, slots=True)
class IngestLimits:
    """The upload limits ingest enforces (spec 10 § 1)."""

    max_pages: int
    max_queue: int
    upload_ttl: dt.timedelta


def pdf_key(sha256: str) -> str:
    """Where the uploaded bytes live."""
    return f"pdf/{sha256}.pdf"


def first_page_key(sha256: str) -> str:
    """The first page image: present exactly while a ready document's files are."""
    return f"pages/{sha256}/1.png"


async def check_pdf(data: bytes, max_pages: int | None) -> int:
    """The page count of an acceptable PDF; raise the matching domain error otherwise."""
    if not data:
        raise EmptyFile
    if PDF_MARKER not in data[:MARKER_WINDOW]:
        raise NotAPdf
    try:
        facts = await asyncio.to_thread(pdf_inspect.inspect_pdf, data)
    except pdf_inspect.PdfEncrypted:
        raise PdfEncrypted from None
    except pdf_inspect.PdfUnreadable:
        raise PdfUnreadable from None
    if max_pages is not None and facts.pages > max_pages:
        raise TooManyPages(
            f"The PDF has {facts.pages} pages; the limit is {max_pages}.",
            detail={"pages": facts.pages, "max_pages": max_pages},
        )
    return facts.pages


class IngestService:
    """Turns uploaded bytes into a document and a queued job, or points at the existing ones."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        stores: Stores,
        *,
        limits: IngestLimits,
        wake: Callable[[], None],
    ) -> None:
        self._sessions = sessions
        self._stores = stores
        self._limits = limits
        self._wake = wake

    async def ingest(
        self, data: bytes, file_name: str | None, *, kind: DocumentKind = "upload"
    ) -> UploadOut:
        """Validate and enqueue. Same bytes while queued, running or ready: deduplicated."""
        # Samples are processed ahead of time, so the live-upload page cap does not apply.
        pages = await check_pdf(data, None if kind == "sample" else self._limits.max_pages)
        sha = hashlib.sha256(data).hexdigest()
        for attempt in range(2):
            try:
                out = await self._enqueue(data, sha, file_name, pages, kind)
            except IntegrityError:
                # A concurrent upload of the same bytes created the document first; look again.
                if attempt:
                    raise
                continue
            if not out.deduplicated:
                self._wake()
            return out
        raise AssertionError  # pragma: no cover - the loop returns or raises

    async def _enqueue(
        self, data: bytes, sha: str, file_name: str | None, pages: int, kind: DocumentKind
    ) -> UploadOut:
        now = dt.datetime.now(dt.UTC)
        async with self._sessions() as s, s.begin():
            doc = await documents.get_by_sha_for_update(s, sha)
            if doc is not None:
                store = self._stores.for_kind(doc.kind)
                if doc.kind == "upload":
                    doc.expires_at = now + self._limits.upload_ttl
                active = await jobs.active_for(s, doc.id)
                if active is not None:
                    return UploadOut(
                        document=document_out(doc, active), job=job_out(active), deduplicated=True
                    )
                # A ready upload whose files a restart lost is processed again.
                if doc.status == "ready" and await store.get(first_page_key(sha)) is not None:
                    latest = await jobs.latest_for(s, doc.id)
                    return UploadOut(
                        document=document_out(doc, latest),
                        job=job_out(latest) if latest else None,
                        deduplicated=True,
                    )
                await self._check_queue(s)
                await store.put(pdf_key(sha), data, "application/pdf")
                job = await jobs.create(s, doc.id)
                doc.status = "queued"
                await s.flush()
                return UploadOut(document=document_out(doc, job), job=job_out(job))
            await self._check_queue(s)
            expires = now + self._limits.upload_ttl if kind == "upload" else None
            doc = await documents.create(
                s,
                sha256=sha,
                file_name=file_name,
                page_count=pages,
                byte_size=len(data),
                kind=kind,
                expires_at=expires,
            )
            await self._stores.for_kind(kind).put(pdf_key(sha), data, "application/pdf")
            job = await jobs.create(s, doc.id)
            return UploadOut(document=document_out(doc, job), job=job_out(job))

    async def _check_queue(self, s: AsyncSession) -> None:
        if await jobs.count_queued(s) >= self._limits.max_queue:
            raise QueueFull
