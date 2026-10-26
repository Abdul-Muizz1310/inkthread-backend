"""The job runner (spec 08 § 4): claim, run the pipeline, persist then broadcast, finish.

One runner task per process. It sleeps on an event that ingest sets and polls every `poll_s`, so a
job enqueued by another instance (or left by a crash and requeued by the reaper) is still picked up.
Each job is one Langfuse trace, `build-document-graph` (spec 14).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from slowquery_detective import request_scope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core import tracing
from inkthread.core.config import LlmMode
from inkthread.domain.digest import link_tables
from inkthread.domain.finalize import ExplainFailed
from inkthread.pipeline.graph import (
    PipelineDeps,
    PipelineFailure,
    PipelineResult,
    Reader,
    StageRun,
    run_pipeline,
)
from inkthread.repositories import documents, events, graphs, jobs, readings
from inkthread.services.broadcast import Broadcast, EventData, StreamEvent
from inkthread.services.ingest import pdf_key
from inkthread.services.llm import AgentFactory, CountingCallLog
from inkthread.services.views import stats_out
from inkthread.storage.blobs import BlobStore
from inkthread.storage.stores import Stores

_log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 2
POLL_S = 5.0
_STRICTNESS = {LlmMode.OFF: 0, LlmMode.REPLAY: 1, LlmMode.LIVE: 2}


def stricter(a: LlmMode, b: LlmMode) -> LlmMode:
    """The more restrictive of two modes: off < replay < live (spec 11 § 3)."""
    return a if _STRICTNESS[a] <= _STRICTNESS[b] else b


def page_png_key(sha256: str, page: int) -> str:
    """A rendered page."""
    return f"pages/{sha256}/{page}.png"


def page_geometry_key(sha256: str, page: int) -> str:
    """A page's word geometry."""
    return f"pages/{sha256}/{page}.json"


def pages_prefix(sha256: str) -> str:
    """Every page blob of a document."""
    return f"pages/{sha256}/"


@dataclass(frozen=True, slots=True)
class _Claimed:
    job_id: uuid.UUID
    document_id: uuid.UUID
    sha256: str
    file_name: str | None
    kind: str
    request_id: str | None


def _attribution(c: _Claimed) -> contextlib.AbstractContextManager[object]:
    """The job's statements count against the request that queued it (spec 13 § 2).

    No stored id: no scope. An id the library refuses never fails the job: it runs unattributed.
    """
    if c.request_id is None:
        return contextlib.nullcontext()
    try:
        return request_scope(c.request_id)
    except (ValueError, TypeError) as exc:
        _log.warning("job_request_id_refused", job_id=str(c.job_id), error=type(exc).__name__)
        return contextlib.nullcontext()


@dataclass(frozen=True, slots=True)
class _Ended:
    """How a job ended, for its trace's root (spec 14 § 2)."""

    status: Literal["succeeded", "failed"]
    code: str | None = None
    graph_hash: str | None = None
    nodes: int | None = None
    edges: int | None = None

    def output(self) -> dict[str, object]:
        if self.status == "failed":
            return {"status": self.status, "error_code": self.code}
        return {
            "status": self.status,
            "graph_hash": self.graph_hash,
            "nodes": self.nodes,
            "edges": self.edges,
        }


def _llm_facts(counter: CountingCallLog, rejected: int = 0) -> dict[str, int]:
    return {
        "requests": counter.requests,
        "cached": counter.cached,
        "failed": counter.failed,
        "rejected": rejected,
    }


def _stage_facts(stages: list[StageRun]) -> list[dict[str, Any]]:
    return [{"name": s.name, "status": s.status, "ms": s.ms, "reason": s.reason} for s in stages]


class JobRunner:
    """Processes queued jobs one at a time."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        stores: Stores,
        broadcast: Broadcast,
        agents: AgentFactory,
        reader: Reader,
        inkgrid_version: str,
        job_timeout_s: float,
        sample_llm_mode: LlmMode = LlmMode.REPLAY,
        poll_s: float = POLL_S,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._sessions = sessions
        self._stores = stores
        self._broadcast = broadcast
        self._agents = agents
        self._reader = reader
        self._inkgrid_version = inkgrid_version
        self._timeout = job_timeout_s
        self._sample_mode = sample_llm_mode
        self._poll = poll_s
        self._max_attempts = max_attempts
        self._wakeup = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def wake(self) -> None:
        """A job was enqueued: stop sleeping."""
        self._wakeup.set()

    async def start(self) -> None:
        """Reap, then process jobs in the background until `stop`."""
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="inkthread-job-runner")

    async def stop(self) -> None:
        """Cancel the background task and wait for it."""
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def reap(self) -> tuple[int, int]:
        """Requeue (or fail as `interrupted`) the jobs a crash left running."""
        async with self._sessions() as s, s.begin():
            requeued, failed = await jobs.reap(s, max_attempts=self._max_attempts)
        if requeued or failed:
            _log.info("jobs_reaped", requeued=requeued, failed=failed)
        return requeued, failed

    async def _loop(self) -> None:
        try:
            await self.reap()
        except Exception as exc:  # noqa: BLE001 - a down database must not kill the service
            _log.warning("reap_failed", error=type(exc).__name__)
        while True:
            self._wakeup.clear()
            try:
                ran = await self.run_once()
            except Exception as exc:  # noqa: BLE001 - keep serving; the job row says what failed
                _log.exception("runner_error", error=type(exc).__name__)
                ran = False
            if not ran:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wakeup.wait(), self._poll)

    async def run_once(self) -> bool:
        """Claim and run the oldest queued job; False when none waits."""
        claimed = await self._claim()
        if claimed is None:
            return False
        log = _log.bind(job_id=str(claimed.job_id), document_id=str(claimed.document_id))
        log.info("job_started")
        store = self._stores.for_kind(claimed.kind)
        try:
            # The job's statements count against the request that queued it (spec 13 § 2).
            with _attribution(claimed):
                await self._run(claimed, store)
        finally:
            if claimed.kind == "upload":  # processed, not kept (spec 08 § 2)
                await store.delete_prefix(pdf_key(claimed.sha256))
        log.info("job_finished")
        return True

    async def _claim(self) -> _Claimed | None:
        async with self._sessions() as s, s.begin():
            job = await jobs.claim_next(s)
            if job is None:
                return None
            doc = await documents.get(s, job.document_id)
            if doc is None:  # pragma: no cover - the foreign key cascades jobs with documents
                return None
            doc.status = "processing"
            return _Claimed(job.id, doc.id, doc.sha256, doc.file_name, doc.kind, job.request_id)

    async def _run(self, c: _Claimed, store: BlobStore) -> None:
        # Anything not a sample is traced as an upload: its text never leaves (spec 14 § 3).
        kind: tracing.DocumentKind = "sample" if c.kind == "sample" else "upload"
        with tracing.job_trace(
            job_id=c.job_id, document_id=c.document_id, kind=kind, file_name=c.file_name
        ) as trace:
            ended = await self._process(c, store)
            failed = ended.status == "failed"
            trace.update(
                output=ended.output(),
                level="ERROR" if failed else None,
                status_message=ended.code if failed else None,
            )

    async def _process(self, c: _Claimed, store: BlobStore) -> _Ended:
        base = self._agents(c.job_id)
        if c.kind == "sample":  # samples replay their recorded answers (spec 11 § 3)
            base = dataclasses.replace(base, mode=stricter(base.mode, self._sample_mode))
        counter = CountingCallLog(base.log)
        deps = PipelineDeps(
            reader=self._reader,
            agents=dataclasses.replace(base, log=counter),
            inkgrid_version=self._inkgrid_version,
        )
        seen: list[StageRun] = []
        pdf = await store.get(pdf_key(c.sha256))
        if pdf is None:
            message = "the upload was not kept across a restart; upload it again"
            return await self._fail(c, "pdf_missing", message, seen)
        outcome: PipelineResult | PipelineFailure | None = None
        stream = run_pipeline(pdf, c.file_name, deps)
        try:
            async with asyncio.timeout(self._timeout):
                async for item in stream:
                    if isinstance(item, PipelineResult | PipelineFailure):
                        outcome = item
                    else:
                        await self._event(c.job_id, item, seen)
        except TimeoutError:
            return await self._fail(
                c, "job_timeout", f"the job ran past {self._timeout:g} s", seen, counter
            )
        except ExplainFailed as exc:
            _log.error("explain_failed", job_id=str(c.job_id), detail=str(exc))
            return await self._fail(
                c, "explain_failed", "the graph failed its explain checks", seen, counter
            )
        except Exception as exc:  # noqa: BLE001 - any pipeline bug fails the job, not the runner
            _log.exception("pipeline_error", job_id=str(c.job_id), error=type(exc).__name__)
            return await self._fail(
                c, "internal_error", "the pipeline stopped unexpectedly", seen, counter
            )
        finally:
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()
        if isinstance(outcome, PipelineResult):
            return await self._succeed(c, outcome, counter, store)
        if isinstance(outcome, PipelineFailure):
            return await self._fail(c, outcome.code, outcome.message, outcome.stages, counter)
        return await self._fail(  # pragma: no cover - run_pipeline always ends with one outcome
            c, "internal_error", "the pipeline ended without a result", seen
        )

    async def _event(self, job_id: uuid.UUID, item: dict[str, Any], seen: list[StageRun]) -> None:
        name = str(item["event"])
        data: EventData = dict(item["data"])
        async with self._sessions() as s, s.begin():
            seq = await events.append(s, job_id, name, data)
            if name == "stage" and data.get("status") == "started":
                await jobs.set_stage(s, job_id, str(data["stage"]))
        if name == "stage" and data.get("status") != "started":
            seen.append(
                StageRun(
                    name=str(data["stage"]),
                    status=data["status"],
                    ms=int(data.get("ms") or 0),
                    reason=data.get("reason"),
                )
            )
        self._broadcast.publish(job_id, StreamEvent(seq, name, data))

    async def _succeed(
        self, c: _Claimed, result: PipelineResult, counter: CountingCallLog, store: BlobStore
    ) -> _Ended:
        graph = result.final.graph
        sha = c.sha256
        # Geometry first and page 1's image last: page 1 marks a ready document's files present.
        for page in range(1, graph.document.page_count + 1):
            words = [
                {"node": w.node, "start": w.start, "end": w.end, "bbox": list(w.bbox)}
                for w in result.geometry.get(page, [])
            ]
            body = json.dumps(words, separators=(",", ":")).encode()
            await store.put(page_geometry_key(sha, page), body, "application/json")
        for n, png in reversed(list(enumerate(result.pngs, start=1))):
            await store.put(page_png_key(sha, n), png, "image/png")
        stats = stats_out(graph.stats.model_dump(mode="json"))
        llm = _llm_facts(counter, sum(r.rejected for r in result.reports.values()))
        done: EventData = {
            "document_id": str(c.document_id),
            "graph_hash": graph.provenance.graph_hash,
            "stats": stats.model_dump(mode="json") if stats else None,
        }
        async with self._sessions() as s, s.begin():
            await graphs.save(
                s,
                c.document_id,
                graph=graph.model_dump(mode="json", by_alias=True),
                graph_hash=graph.provenance.graph_hash,
                ops=[op.model_dump(mode="json") for op in result.final.ops],
            )
            await readings.save(
                s,
                c.document_id,
                inkgrid_version=result.digest.inkgrid_version,
                verification=result.digest.verification.model_dump(mode="json"),
                tables=[t.model_dump(mode="json") for t in link_tables(result.digest, graph)],
                findings=[f.model_dump(mode="json") for f in result.digest.findings],
            )
            await documents.set_status(s, c.document_id, "ready", title=graph.document.title)
            await jobs.finish(
                s, c.job_id, status="succeeded", stages=_stage_facts(result.stages), llm=llm
            )
            seq = await events.append(s, c.job_id, "done", done)
        self._broadcast.publish(c.job_id, StreamEvent(seq, "done", done))
        return _Ended(
            "succeeded",
            graph_hash=graph.provenance.graph_hash,
            nodes=len(graph.nodes),
            edges=len(graph.edges),
        )

    async def _fail(
        self,
        c: _Claimed,
        code: str,
        message: str,
        stages: list[StageRun],
        counter: CountingCallLog | None = None,
    ) -> _Ended:
        _log.info("job_failed", job_id=str(c.job_id), code=code)
        failed: EventData = {"code": code, "message": message}
        async with self._sessions() as s, s.begin():
            await documents.set_status(s, c.document_id, "failed")
            await jobs.finish(
                s,
                c.job_id,
                status="failed",
                stages=_stage_facts(stages),
                llm=_llm_facts(counter) if counter else {},
                error_code=code,
                error_message=message,
            )
            seq = await events.append(s, c.job_id, "failed", failed)
        self._broadcast.publish(c.job_id, StreamEvent(seq, "failed", failed))
        return _Ended("failed", code=code)
