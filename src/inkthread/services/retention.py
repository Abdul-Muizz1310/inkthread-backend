"""The sweep (spec 08 § 4): uploads whose time is up, or whose files are gone, are deleted."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.models import Document
from inkthread.repositories import documents
from inkthread.services.ingest import first_page_key, pdf_key
from inkthread.services.runner import pages_prefix
from inkthread.storage.stores import Stores

_log = structlog.get_logger(__name__)

SWEEP_EVERY_S = 300.0


class RetentionSweeper:
    """Deletes expired and orphaned uploads; `start` sweeps now, then every `interval_s`."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        stores: Stores,
        *,
        interval_s: float = SWEEP_EVERY_S,
    ) -> None:
        self._sessions = sessions
        self._uploads = stores.uploads
        self._interval = interval_s
        self._task: asyncio.Task[None] | None = None

    async def _doomed(self, doc: Document, now: dt.datetime) -> bool:
        if doc.kind != "upload":
            return False
        if doc.expires_at is not None and doc.expires_at < now:
            return True
        return doc.status == "ready" and await self._uploads.get(first_page_key(doc.sha256)) is None

    async def _drop(self, sha: str, now: dt.datetime) -> bool:
        """Delete one upload if it is still doomed under its row lock: an upload of the same bytes
        may have renewed or requeued it since the sweep looked."""
        async with self._sessions() as s, s.begin():
            doc = await documents.get_by_sha_for_update(s, sha)
            if doc is None or not await self._doomed(doc, now):
                return False
            await documents.delete(s, doc.id)
        await self._uploads.delete_prefix(pdf_key(sha))
        await self._uploads.delete_prefix(pages_prefix(sha))
        return True

    async def sweep(self, now: dt.datetime) -> int:
        """Delete every upload that expired before `now`, and every ready upload whose first page
        image is gone from this instance; samples are never swept. Returns how many went."""
        async with self._sessions() as s:
            expired = [d.sha256 for d in await documents.expired_uploads(s, now)]
            ready = [d.sha256 for d in await documents.ready_uploads(s)]
        deleted = 0
        for sha in dict.fromkeys([*expired, *ready]):
            deleted += await self._drop(sha, now)
        if deleted:
            _log.info("uploads_swept", deleted=deleted)
        return deleted

    async def start(self) -> None:
        """Sweep now, then every `interval_s`."""
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="inkthread-sweep")

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
            except Exception as exc:  # noqa: BLE001 - try again at the next interval
                _log.warning("sweep_failed", error=type(exc).__name__)
            await asyncio.sleep(self._interval)
