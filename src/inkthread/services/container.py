"""Every service the app uses, built once in the lifespan and shared by the routers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.services.broadcast import Broadcast
from inkthread.services.documents import DocumentService
from inkthread.services.ingest import IngestService
from inkthread.services.retention import RetentionSweeper
from inkthread.services.runner import JobRunner
from inkthread.services.streams import StreamService


@dataclass(frozen=True)
class Services:
    """The app's use cases and background workers."""

    sessions: async_sessionmaker[AsyncSession]
    broadcast: Broadcast
    ingest: IngestService
    documents: DocumentService
    streams: StreamService
    runner: JobRunner
    retention: RetentionSweeper
