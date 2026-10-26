"""Spec 14 § 2 `recall-answer`: the lookup of a recorded answer is a retriever (T-TR-8).

The lookups run as a sample's, so their output and metadata reach the exporter (spec 14 § 3).
"""

from __future__ import annotations

from agent_drafts import deps
from fake_llm import MemoryStore, Reply, ScriptedModel
from langfuse import propagate_attributes
from pydantic import BaseModel, ConfigDict
from tracing_support import OUTPUT, Traces

from inkthread.agents.prompts import load_prompt
from inkthread.agents.runner import TaskOutcome, run_task
from inkthread.core.config import LlmMode

SCHEMA: dict[str, object] = {"type": "object"}


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: list[str]


async def run(
    model: ScriptedModel, store: MemoryStore, mode: LlmMode = LlmMode.LIVE
) -> TaskOutcome[Answer]:
    with propagate_attributes(tags=["inkthread", "kind:sample"]):
        return await run_task(
            prompt=load_prompt("classify"),
            answer_model=Answer,
            schema=SCHEMA,
            payload={"parts": [1]},
            cascade=("p/primary:free",),
            deps=deps(model, mode=mode, store=store),
        )


async def test_a_live_miss_is_a_miss_then_the_model(traces: Traces) -> None:
    model = ScriptedModel([Reply('{"labels": ["a"]}')])
    out = await run(model, MemoryStore())
    assert out.status == "answered"
    recall = traces.one("recall-answer")
    assert traces.type_of(recall) == "retriever"
    assert traces.metadata(recall) == {"task": "classify", "hit": False}
    assert traces.attr(recall, OUTPUT) is None
    assert len(model.requests) == 1


async def test_a_recorded_hit_is_a_hit_and_no_model_call(traces: Traces) -> None:
    store = MemoryStore()
    await run(ScriptedModel([Reply('{"labels": ["a"]}')]), store)
    traces.clear()
    again = ScriptedModel([])
    out = await run(again, store)
    assert out.status == "cached"
    recall = traces.one("recall-answer")
    assert traces.metadata(recall) == {
        "task": "classify",
        "hit": True,
        "served_model": "fake/producer",
    }
    assert traces.decoded(recall, OUTPUT) == {"labels": ["a"]}
    assert again.requests == []


async def test_a_record_that_no_longer_validates_is_a_miss(traces: Traces) -> None:
    store = MemoryStore()
    await run(ScriptedModel([Reply('{"labels": ["a"]}')]), store)
    (key,) = store.records
    store.records[key] = store.records[key].__class__(
        key=key,
        task="classify",
        served_model="fake/producer",
        response={"labels": 7},
        created_at=store.records[key].created_at,
    )
    traces.clear()
    out = await run(ScriptedModel([Reply('{"labels": ["b"]}')]), store)
    assert out.status == "answered"
    assert traces.metadata(traces.one("recall-answer"))["hit"] is False


async def test_a_replay_miss_is_only_the_lookup(traces: Traces) -> None:
    model = ScriptedModel([])
    out = await run(model, MemoryStore(), LlmMode.REPLAY)
    assert out.reason == "replay_miss"
    assert [s.name for s in traces.spans()] == ["recall-answer"]
    assert model.requests == []


async def test_mode_off_traces_nothing(traces: Traces) -> None:
    out = await run(ScriptedModel([]), MemoryStore(), LlmMode.OFF)
    assert out.reason == "disabled"
    assert traces.spans() == []
