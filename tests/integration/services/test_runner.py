"""Plan Task 17: ingest, the job runner, the reaper and retention against real Postgres."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import pdfs
import pytest
from fake_llm import MemoryCallLog, MemoryStore, ScriptedModel
from inproc import read_inprocess
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.agents.deps import AgentDeps
from inkthread.core.config import LlmMode
from inkthread.core.errors import QueueFull
from inkthread.reader.process import ReadFailure, ReadOutcome
from inkthread.repositories import documents, events, graphs, jobs
from inkthread.services.broadcast import Broadcast, StreamEvent
from inkthread.services.ingest import IngestLimits, IngestService
from inkthread.services.retention import RetentionSweeper
from inkthread.services.runner import JobRunner
from inkthread.storage.blobs import LocalBlobStore

pytestmark = pytest.mark.integration

LIMITS = IngestLimits(max_pages=40, max_queue=10, retention_days=7)


def agents(_job_id: uuid.UUID) -> AgentDeps:
    return AgentDeps(
        model=ScriptedModel(script=[]),
        store=MemoryStore(),
        log=MemoryCallLog(),
        mode=LlmMode.OFF,
        producer_cascade=("fake/producer",),
        verifier_cascade=("fake/verifier",),
    )


class Harness:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], root: Path) -> None:
        self.sessions = sessions
        self.blobs = LocalBlobStore(root)
        self.broadcast = Broadcast()
        self.woken = 0
        self.ingest = IngestService(sessions, self.blobs, limits=LIMITS, wake=self._wake)

    def _wake(self) -> None:
        self.woken += 1

    def runner(self, reader: object = read_inprocess) -> JobRunner:
        return JobRunner(
            sessions=self.sessions,
            blobs=self.blobs,
            broadcast=self.broadcast,
            agents=agents,
            reader=reader,  # type: ignore[arg-type]
            inkgrid_version="0.1.0",
            job_timeout_s=60,
        )


@pytest.fixture
def h(sessions: async_sessionmaker[AsyncSession], tmp_path: Path) -> Harness:
    return Harness(sessions, tmp_path)


async def test_ingest_dedupes_and_requeues(h: Harness) -> None:
    first = await h.ingest.ingest(pdfs.sectioned(), "a.pdf")
    assert first.deduplicated is False
    assert h.woken == 1
    again = await h.ingest.ingest(pdfs.sectioned(), "b.pdf")
    assert again.deduplicated is True
    assert again.job is not None
    assert first.job is not None
    assert again.job.id == first.job.id
    assert h.woken == 1
    async with h.sessions() as s, s.begin():
        await jobs.finish(s, first.job.id, status="failed", stages=[], llm={}, error_code="x")
        await documents.set_status(s, first.document.id, "failed")
    requeued = await h.ingest.ingest(pdfs.sectioned(), "c.pdf")
    assert requeued.deduplicated is False
    assert requeued.job is not None
    assert requeued.job.id != first.job.id
    assert h.woken == 2


async def test_ingest_refuses_when_the_queue_is_full(h: Harness) -> None:
    small = IngestService(
        h.sessions,
        h.blobs,
        limits=IngestLimits(max_pages=40, max_queue=1, retention_days=7),
        wake=lambda: None,
    )
    await small.ingest(pdfs.sectioned(), None)
    with pytest.raises(QueueFull):
        await small.ingest(pdfs.two_pages(), None)


async def test_runner_persists_each_event_before_broadcasting_it(h: Harness) -> None:
    up = await h.ingest.ingest(pdfs.sectioned(), "a.pdf")
    assert up.job is not None
    job_id = up.job.id
    seen: list[StreamEvent] = []
    persisted: set[int] = set()
    persisted_at_publish: list[bool] = []
    publish = h.broadcast.publish

    def checking_publish(jid: uuid.UUID, event: StreamEvent) -> None:
        seen.append(event)
        persisted_at_publish.append(event.seq in persisted)
        publish(jid, event)

    real_append = events.append

    async def tracking_append(
        s: AsyncSession, jid: uuid.UUID, type_: str, payload: dict[str, Any]
    ) -> int:
        seq = await real_append(s, jid, type_, payload)
        persisted.add(seq)
        return seq

    h.broadcast.publish = checking_publish  # type: ignore[method-assign]
    mp = pytest.MonkeyPatch()
    mp.setattr(events, "append", tracking_append)
    try:
        assert await h.runner().run_once() is True
    finally:
        mp.undo()
    assert all(persisted_at_publish)
    assert [e.seq for e in seen] == list(range(1, len(seen) + 1))
    async with h.sessions() as s:
        rows = await events.after(s, job_id, 0)
        assert [(r.seq, r.type, r.payload) for r in rows] == [(e.seq, e.type, e.data) for e in seen]
        assert rows[-1].type == "done"
        job = await jobs.get(s, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert [st["name"] for st in job.stages][-1] == "finalize"
        assert set(job.llm) == {"requests", "cached", "failed", "rejected"}
        doc = await documents.get(s, up.document.id)
        assert doc is not None
        assert doc.status == "ready"
        assert doc.title == pdfs.SECTIONED_TITLE
        row = await graphs.get(s, up.document.id)
        assert row is not None
        assert row.graph_hash == rows[-1].payload["graph_hash"]
        assert row.graph["schema"] == "inkthread.graph/1"
    sha = up.document.sha256
    assert (await h.blobs.get(f"pages/{sha}/1.png")) == b"png"
    geometry = json.loads((await h.blobs.get(f"pages/{sha}/1.json")) or b"null")
    assert geometry
    assert set(geometry[0]) == {"node", "start", "end", "bbox"}
    assert await h.runner().run_once() is False


async def test_runner_records_a_failure_code(h: Harness) -> None:
    async def failing(_pdf: bytes) -> ReadOutcome:
        return ReadFailure("no_text_layer", "the PDF has no text layer")

    up = await h.ingest.ingest(pdfs.sectioned(), None)
    assert up.job is not None
    sub = h.broadcast.subscribe(up.job.id)
    assert await h.runner(failing).run_once() is True
    async with h.sessions() as s:
        job = await jobs.get(s, up.job.id)
        doc = await documents.get(s, up.document.id)
        rows = await events.after(s, up.job.id, 0)
    assert job is not None
    assert doc is not None
    assert (job.status, job.error_code) == ("failed", "no_text_layer")
    assert doc.status == "failed"
    assert rows[-1].type == "failed"
    assert rows[-1].payload == {"code": "no_text_layer", "message": "the PDF has no text layer"}
    live = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    assert [e.seq for e in live] == [r.seq for r in rows]
    sub.close()


async def test_runner_fails_a_job_whose_reader_crashes(h: Harness) -> None:
    async def crashing(_pdf: bytes) -> ReadOutcome:
        msg = "boom"
        raise RuntimeError(msg)

    up = await h.ingest.ingest(pdfs.sectioned(), None)
    assert up.job is not None
    assert await h.runner(crashing).run_once() is True
    async with h.sessions() as s:
        job = await jobs.get(s, up.job.id)
    assert job is not None
    assert (job.status, job.error_code) == ("failed", "internal_error")


async def test_runner_start_reaps_then_processes(h: Harness) -> None:
    up = await h.ingest.ingest(pdfs.sectioned(), None)
    assert up.job is not None
    async with h.sessions() as s, s.begin():
        await jobs.claim_next(s)  # a crash left it running
    runner = h.runner()
    assert await runner.reap() == (1, 0)
    async with h.sessions() as s:
        job = await jobs.get(s, up.job.id)
    assert job is not None
    assert (job.status, job.attempt) == ("queued", 2)
    async with h.sessions() as s, s.begin():
        await jobs.claim_next(s)
    assert await runner.reap() == (0, 1)
    async with h.sessions() as s:
        job = await jobs.get(s, up.job.id)
    assert job is not None
    assert (job.status, job.error_code) == ("failed", "interrupted")


async def test_retention_deletes_expired_uploads_and_their_blobs(h: Harness) -> None:
    old = await h.ingest.ingest(pdfs.sectioned(), None)
    fresh = await h.ingest.ingest(pdfs.two_pages(), None)
    await h.blobs.put(f"pages/{old.document.sha256}/1.png", b"png", "image/png")
    sweeper = RetentionSweeper(h.sessions, h.blobs)
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=7, hours=1)
    async with h.sessions() as s, s.begin():
        doc = await documents.get(s, fresh.document.id)
        assert doc is not None
        doc.expires_at = later + dt.timedelta(days=1)
    assert await sweeper.sweep(later) == 1
    async with h.sessions() as s:
        assert await documents.get(s, old.document.id) is None
        assert await documents.get(s, fresh.document.id) is not None
    assert await h.blobs.get(f"pdf/{old.document.sha256}.pdf") is None
    assert await h.blobs.get(f"pages/{old.document.sha256}/1.png") is None
    assert await h.blobs.get(f"pdf/{fresh.document.sha256}.pdf") is not None
