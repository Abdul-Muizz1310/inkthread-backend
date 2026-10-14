"""Task 14: the composed pipeline on synthetic PDFs (real inkgrid, no network)."""

from __future__ import annotations

import pdfs
import pytest
from fake_llm import MemoryCallLog, MemoryStore, Reply, ScriptedModel
from inproc import read_inprocess

from inkthread.agents.deps import AgentDeps
from inkthread.core.config import LlmMode
from inkthread.pipeline.graph import PipelineDeps, PipelineFailure, PipelineResult, run_pipeline

pytestmark = pytest.mark.integration


def deps(mode: LlmMode, model: ScriptedModel | None = None) -> PipelineDeps:
    agents = AgentDeps(
        model=model or ScriptedModel(script=[]),
        store=MemoryStore(),
        log=MemoryCallLog(),
        mode=mode,
        producer_cascade=("fake/producer",),
        verifier_cascade=("fake/verifier",),
    )
    return PipelineDeps(reader=read_inprocess, agents=agents)


async def run(pdf: bytes, d: PipelineDeps) -> tuple[list[dict], PipelineResult | PipelineFailure]:
    events: list[dict] = []
    out: PipelineResult | PipelineFailure | None = None
    async for item in run_pipeline(pdf, "doc.pdf", d):
        if isinstance(item, (PipelineResult, PipelineFailure)):
            out = item
        else:
            events.append(item)
    assert out is not None
    return events, out


async def test_stages_run_in_order_and_the_graph_is_valid() -> None:
    events, out = await run(pdfs.sectioned(), deps(LlmMode.OFF))
    assert isinstance(out, PipelineResult)
    names = [s.name for s in out.stages]
    assert names == [
        "read",
        "structure",
        "classify_rules",
        "classify_agent",
        "link_rules",
        "relate_agent",
        "verify_agent",
        "finalize",
    ]
    by = {s.name: s for s in out.stages}
    assert by["classify_agent"].status == "skipped"
    graph = out.final.graph
    assert graph.document.file_name == "doc.pdf"
    assert any(n.kind == "section" for n in graph.nodes)
    assert any(e["event"] == "delta" for e in events)
    assert events[0] == {
        "event": "stage",
        "data": {"stage": "read", "status": "started", "ms": 0, "reason": None, "counts": None},
    }


async def test_replay_is_byte_identical() -> None:  # G7 (spec 08 T-PJ-13, rules-only half)
    _, a = await run(pdfs.footnoted(), deps(LlmMode.OFF))
    _, b = await run(pdfs.footnoted(), deps(LlmMode.OFF))
    assert isinstance(a, PipelineResult) and isinstance(b, PipelineResult)
    assert a.final.graph.provenance.graph_hash == b.final.graph.provenance.graph_hash
    assert a.final.graph.model_dump_json() == b.final.graph.model_dump_json()


async def test_a_junk_model_answer_never_breaks_the_graph() -> None:
    model = ScriptedModel(script=[Reply('{"labels": "nope"}')] * 10)
    _, out = await run(pdfs.sectioned(), deps(LlmMode.LIVE, model))
    assert isinstance(out, PipelineResult)


async def test_an_unreadable_pdf_fails_cleanly() -> None:
    _, out = await run(pdfs.garbage(), deps(LlmMode.OFF))
    assert isinstance(out, PipelineFailure)
    assert out.code == "pdf_unreadable"
    assert [s.status for s in out.stages] == ["failed"]
