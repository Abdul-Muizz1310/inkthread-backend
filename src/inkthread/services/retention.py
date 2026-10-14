"""Retention (spec 08 § 4): uploads past `expires_at` are deleted with their blobs; samples stay."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.repositories import documents
from inkthread.services.ingest import pdf_key
from inkthread.services.runner import pages_prefix
from inkthread.storage.blobs import BlobStore

_log = structlog.get_logger(__name__)

SWEEP_EVERY_S = 3600.0


class RetentionSweeper:
    """Deletes expired uploads; `start` runs a sweep every `interval_s`."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        blobs: BlobStore,
        *,
        interval_s: float = SWEEP_EVERY_S,
        blob_budget_bytes: int | None = None,
        usage: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        self._sessions = sessions
        self._blobs = blobs
        self._interval = interval_s
        self._budget = blob_budget_bytes
        self._usage = usage
        self._task: asyncio.Task[None] | None = None

    async def _drop(self, doc_id: uuid.UUID, sha: str) -> None:
        async with self._sessions() as s, s.begin():
            await documents.delete(s, doc_id)
        await self._blobs.delete_prefix(pdf_key(sha))
        await self._blobs.delete_prefix(pages_prefix(sha))

    async def sweep(self, now: dt.datetime) -> int:
        """Delete every upload that expired before `now`, then the oldest uploads while the blob
        budget is exceeded (samples are never evicted); returns how many were deleted."""
        async with self._sessions() as s:
            expired = [(d.id, d.sha256) for d in await documents.expired_uploads(s, now)]
        for doc_id, sha in expired:
            await self._drop(doc_id, sha)
        deleted = len(expired)
        if self._budget is not None and self._usage is not None:
            async with self._sessions() as s:
                oldest = [(d.id, d.sha256) for d in await documents.uploads_oldest_first(s)]
            for doc_id, sha in oldest:
                if await self._usage() <= self._budget:
                    break
                await self._drop(doc_id, sha)
                deleted += 1
        if deleted:
            _log.info("retention_swept", deleted=deleted)
        return deleted

    async def start(self) -> None:
        """Sweep now, then hourly."""
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="inkthread-retention")

    async def stop(self) -> None:
        """Cancel the sweeper."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        while True:
            try:
                await self.sweep(dt.datetime.now(dt.UTC))
            except Exception as exc:  # noqa: BLE001 - try again next hour
                _log.warning("retention_failed", error=type(exc).__name__)
            await asyncio.sleep(self._interval)
