"""The LangGraph pipeline (spec 00 § 4): read, structure, classify, link, relate, verify, finalize.

Nodes are thin shells over the pure domain and the agent layer. They report progress through
LangGraph's custom stream (`stage`, `delta` and `llm` events) and never touch the database: the job
runner persists what they stream. Each runs inside its Langfuse observation (spec 14 § 2).
"""

from __future__ import annotations

import itertools
import operator
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from inkthread import PIPELINE_VERSION
from inkthread.agents.classify import classify_agent
from inkthread.agents.deps import AgentDeps, AgentReport
from inkthread.agents.prompts import prompts_hash
from inkthread.agents.relate import relate_agent
from inkthread.agents.verify import verify_agent
from inkthread.core import tracing
from inkthread.domain.classify.residual import residual
from inkthread.domain.classify.rules import classify
from inkthread.domain.digest import ReadingDigest
from inkthread.domain.draft import GraphDraft
from inkthread.domain.finalize import FinalGraph, finalize
from inkthread.domain.link.build import link_rules
from inkthread.domain.reading import Reading
from inkthread.domain.sketches import sketch
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.types import GeomWord, StructureResult
from inkthread.llm.ports import CallLog, LlmCall
from inkthread.reader.process import ReadFailure, ReadOutcome

Reader = Callable[[bytes], Awaitable[ReadOutcome]]
StageStatus = Literal["started", "completed", "skipped", "failed"]


@dataclass(frozen=True)
class StageRun:
    """One stage's outcome, kept on the job (spec 06 § 5: run facts stay out of the graph)."""

    name: str
    status: StageStatus
    ms: int
    reason: str | None = None
    # For the trace only: the job row keeps name, status, ms and reason (spec 08).
    counts: tuple[tuple[str, int], ...] = field(default=(), compare=False)


@dataclass
class PipelineResult:
    """Everything a successful run produced."""

    final: FinalGraph
    pngs: list[bytes]
    geometry: dict[int, list[GeomWord]]
    stages: list[StageRun]
    reports: dict[str, AgentReport]
    digest: ReadingDigest


@dataclass
class PipelineFailure:
    """A run that stopped; `code` becomes the job's error code."""

    code: str
    message: str
    stages: list[StageRun] = field(default_factory=list)


class State(TypedDict, total=False):
    """The pipeline's state. Heavy values live in memory only (no checkpointer, spec 00 D-5)."""

    pdf: bytes
    file_name: str | None
    reading: Reading
    pngs: list[bytes]
    digest: ReadingDigest
    draft: GraphDraft
    structure: StructureResult
    failure: ReadFailure
    final: FinalGraph
    stages: Annotated[list[StageRun], operator.add]
    reports: Annotated[list[tuple[str, AgentReport]], operator.add]


def _emit(event: str, data: Mapping[str, Any]) -> None:
    get_stream_writer()({"event": event, "data": dict(data)})


def _stage(
    name: str,
    status: StageStatus,
    ms: int = 0,
    reason: str | None = None,
    counts: Mapping[str, int] | None = None,
) -> StageRun:
    _emit(
        "stage",
        {
            "stage": name,
            "status": status,
            "ms": ms,
            "reason": reason,
            "counts": dict(counts) if counts else None,
        },
    )
    return StageRun(
        name=name, status=status, ms=ms, reason=reason, counts=tuple((counts or {}).items())
    )


def _delta(draft: GraphDraft, stage: str) -> None:
    batch = sketch(draft.take_delta(), stage)
    if batch.nodes or batch.edges or batch.roles or batch.flags:
        _emit("delta", batch.model_dump(mode="json"))


class StreamingCallLog:
    """Forwards every traced call to the real log and to the live event stream."""

    def __init__(self, inner: CallLog) -> None:
        self._inner = inner

    async def record(self, call: LlmCall) -> None:
        await self._inner.record(call)
        _emit(
            "llm",
            {
                "task": call.task,
                "model": call.model,
                "cached": call.cached,
                "ok": call.status in {"ok", "cached"},
                "status": call.status,
                "ms": call.latency_ms,
            },
        )


@dataclass(frozen=True)
class PipelineDeps:
    """What a run needs from outside the domain."""

    reader: Reader
    agents: AgentDeps
    inkgrid_version: str = "0.1.0"


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class Node(Protocol):
    """A pipeline node, as LangGraph calls it."""

    def __call__(self, state: State) -> Awaitable[dict[str, Any]]: ...


#: Each stage's Langfuse observation (spec 14 § 2): its name and type.
OBSERVED: dict[str, tuple[str, tracing.StepType]] = {
    "read": ("read-pdf", "chain"),
    "structure": ("build-structure", "chain"),
    "classify_rules": ("classify-by-rules", "chain"),
    "classify_agent": ("classify-parts", "agent"),
    "link_rules": ("link-by-rules", "chain"),
    "relate_agent": ("relate-parts", "agent"),
    "verify_agent": ("verify-claims", "evaluator"),
    "finalize": ("finalize-graph", "chain"),
}
#: Batch-level reasons an operator should see; `no_input`, `disabled`, `replay_miss` are expected.
_WARNING_REASONS = frozenset({"budget", "model_unavailable", "invalid_answer"})


def _observed(name: str, node: Node) -> Node:
    """`node` inside its stage's observation, which records how the stage ended."""
    title, kind = OBSERVED[name]

    async def run(state: State) -> dict[str, Any]:
        with tracing.step(title, as_type=kind, metadata={"stage": name}) as observation:
            update = await node(state)
            for stage in update.get("stages", []):
                level: Literal["WARNING", "ERROR"] | None = None
                if stage.status == "failed":
                    level = "ERROR"
                elif stage.reason in _WARNING_REASONS:
                    level = "WARNING"
                facts: dict[str, object] = {"status": stage.status, **dict(stage.counts)}
                if stage.reason is not None:
                    facts["reason"] = stage.reason
                observation.update(
                    metadata=facts, level=level, status_message=stage.reason if level else None
                )
            return update

    return run


def build_pipeline(deps: PipelineDeps) -> Any:  # noqa: ANN401, PLR0915 - LangGraph's graph type; one closure per stage
    """Compile the state graph over `deps`."""
    agents = AgentDeps(**{**deps.agents.__dict__, "log": StreamingCallLog(deps.agents.log)})

    async def read(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        _stage("read", "started")
        outcome = await deps.reader(state["pdf"])
        if isinstance(outcome, ReadFailure):
            return {
                "failure": outcome,
                "stages": [_stage("read", "failed", _ms(start), outcome.code)],
            }
        reading = outcome.reading.model_copy(update={"file_name": state.get("file_name")})
        draft = GraphDraft(
            sha256=reading.sha256, pipeline_version=PIPELINE_VERSION, file_name=reading.file_name
        )
        done = _stage(
            "read",
            "completed",
            _ms(start),
            counts={"pages": len(reading.pages), "blocks": len(reading.blocks)},
        )
        return {
            "reading": reading,
            "pngs": outcome.pngs,
            "digest": outcome.digest,
            "draft": draft,
            "stages": [done],
        }

    def after_read(state: State) -> str:
        return END if "failure" in state else "structure"

    async def structure(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        _stage("structure", "started")
        draft = state["draft"]
        result = build_structure(state["reading"], draft)
        _delta(draft, "structure")
        done = _stage(
            "structure",
            "completed",
            _ms(start),
            counts={"nodes": len(draft.nodes), "set_aside": len(draft.set_aside)},
        )
        return {"structure": result, "stages": [done]}

    async def classify_rules(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        _stage("classify_rules", "started")
        draft = state["draft"]
        classify(draft)
        _delta(draft, "classify_rules")
        return {"stages": [_stage("classify_rules", "completed", _ms(start))]}

    async def agent_stage(
        name: str, run: Callable[[], Awaitable[AgentReport]], draft: GraphDraft, *, empty: bool
    ) -> dict[str, Any]:
        start = time.perf_counter()
        _stage(name, "started")
        if empty:
            return {"stages": [_stage(name, "skipped", 0, "no_input")]}
        report = await run()
        _delta(draft, name)
        status: StageStatus = (
            "skipped" if report.skipped_reason and not report.accepted else "completed"
        )
        return {
            "stages": [
                _stage(
                    name,
                    status,
                    _ms(start),
                    report.skipped_reason,
                    {"accepted": report.accepted, "rejected": report.rejected},
                )
            ],
            "reports": [(name, report)],
        }

    async def classify_agent_node(state: State) -> dict[str, Any]:
        draft = state["draft"]
        todo = residual(draft)
        return await agent_stage(
            "classify_agent", lambda: classify_agent(draft, todo, agents), draft, empty=not todo
        )

    async def link(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        _stage("link_rules", "started")
        draft = state["draft"]
        link_rules(draft, state["structure"].sections)
        _delta(draft, "link_rules")
        return {
            "stages": [
                _stage("link_rules", "completed", _ms(start), counts={"edges": len(draft.edges)})
            ]
        }

    async def relate(state: State) -> dict[str, Any]:
        draft = state["draft"]
        return await agent_stage(
            "relate_agent", lambda: relate_agent(draft, agents), draft, empty=False
        )

    async def verify(state: State) -> dict[str, Any]:
        draft = state["draft"]
        claims = any(e.basis.value == "semantic" for e in draft.edges.values()) or any(
            r.basis.value == "semantic" for n in draft.nodes.values() for r in n.roles.values()
        )
        return await agent_stage(
            "verify_agent", lambda: verify_agent(draft, agents), draft, empty=not claims
        )

    async def finish(state: State) -> dict[str, Any]:
        start = time.perf_counter()
        _stage("finalize", "started")
        final = finalize(
            state["draft"],
            state["reading"],
            inkgrid_version=deps.inkgrid_version,
            prompts_hash=prompts_hash(),
            models={
                "producer": " > ".join(agents.producer_cascade),
                "verifier": " > ".join(agents.verifier_cascade),
            },
        )
        return {"final": final, "stages": [_stage("finalize", "completed", _ms(start))]}

    builder = StateGraph(State)
    for name, fn in (
        ("read", read),
        ("structure", structure),
        ("classify_rules", classify_rules),
        ("classify_agent", classify_agent_node),
        ("link_rules", link),
        ("relate_agent", relate),
        ("verify_agent", verify),
        ("finalize", finish),
    ):
        builder.add_node(name, _observed(name, fn))
    builder.add_edge(START, "read")
    builder.add_conditional_edges("read", after_read, ["structure", END])
    chain = [
        "structure",
        "classify_rules",
        "classify_agent",
        "link_rules",
        "relate_agent",
        "verify_agent",
        "finalize",
    ]
    for a, b in itertools.pairwise(chain):
        builder.add_edge(a, b)
    builder.add_edge("finalize", END)
    return builder.compile()


PipelineEvent = dict[str, Any]


async def run_pipeline(
    pdf: bytes, file_name: str | None, deps: PipelineDeps
) -> AsyncIterator[PipelineEvent | PipelineResult | PipelineFailure]:
    """Stream events, then yield exactly one result or failure."""
    graph = build_pipeline(deps)
    final_state: dict[str, Any] = {}
    async for mode, chunk in graph.astream(
        {"pdf": pdf, "file_name": file_name, "stages": [], "reports": []},
        stream_mode=["custom", "values"],
    ):
        if mode == "custom":
            yield chunk
        else:
            final_state = chunk
    stages: list[StageRun] = final_state.get("stages", [])
    failure: ReadFailure | None = final_state.get("failure")
    if failure is not None:
        yield PipelineFailure(code=failure.code, message=failure.message, stages=stages)
        return
    structure: StructureResult = final_state["structure"]
    yield PipelineResult(
        final=final_state["final"],
        pngs=final_state["pngs"],
        geometry=structure.geometry,
        stages=stages,
        reports=dict(final_state.get("reports", [])),
        digest=final_state["digest"],
    )
