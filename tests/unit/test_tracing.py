"""Spec 14: client (T-TR-1), usage and cost (T-TR-2), upload mask (T-TR-3), steps (T-TR-4)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

import pytest
from langfuse import propagate_attributes
from tracing_support import INPUT, OUTPUT, Traces

from inkthread.core import tracing
from inkthread.core.config import Settings

SECRET = "Confidential fee schedule for Acme"


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, database_url="postgresql://x/y", llm_mode="off", **overrides)


class Recorder:
    seen: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        Recorder.seen = kwargs


# T-TR-1 ----------------------------------------------------------------------------------------


def test_both_keys_build_an_enabled_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "Langfuse", Recorder)
    tracing.build_client(
        settings(
            langfuse_public_key="pk-lf-1",
            langfuse_secret_key="sk-lf-1",
            langfuse_base_url="https://us.cloud.langfuse.com",
            app_env="production",
        )
    )
    assert Recorder.seen == {
        "public_key": "pk-lf-1",
        "secret_key": "sk-lf-1",
        "base_url": "https://us.cloud.langfuse.com",
        "environment": "production",
        "mask_otel_spans": tracing.withhold_upload_text,
    }


def test_no_base_url_leaves_the_sdk_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "Langfuse", Recorder)
    tracing.build_client(settings(langfuse_public_key="pk", langfuse_secret_key="sk"))
    assert Recorder.seen["base_url"] is None
    assert Recorder.seen["environment"] == "development"


@pytest.mark.parametrize(
    "keys",
    [
        {},
        {"langfuse_public_key": "pk-lf-1"},
        {"langfuse_secret_key": "sk-lf-1"},
        {"langfuse_public_key": "", "langfuse_secret_key": "sk-lf-1"},
        {"langfuse_public_key": "pk-lf-1", "langfuse_secret_key": "  "},
    ],
)
def test_a_missing_or_blank_key_disables_tracing(
    monkeypatch: pytest.MonkeyPatch, keys: dict[str, str]
) -> None:
    monkeypatch.setattr(tracing, "Langfuse", Recorder)
    tracing.build_client(settings(**keys))
    assert Recorder.seen == {"tracing_enabled": False}


def test_a_disabled_client_traces_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = tracing.build_client(settings())
    monkeypatch.setattr(tracing._state, "client", client)
    with tracing.step("read-pdf", as_type="chain", metadata={"stage": "read"}) as step:
        step.update(metadata={"status": "completed"})
        assert client.get_current_trace_id() is None


def test_configure_with_both_keys_installs_the_built_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[Settings] = []

    def build(cfg: Settings) -> str:
        built.append(cfg)
        return "built"

    cfg = settings(langfuse_public_key="pk-lf-1", langfuse_secret_key="sk-lf-1")
    monkeypatch.setattr(tracing._state, "client", None)
    monkeypatch.setattr(tracing, "build_client", build)
    tracing.configure(cfg)
    assert tracing.client() == "built"
    assert built == [cfg]


def test_configure_without_keys_leaves_the_client_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    current = object()
    monkeypatch.setattr(tracing._state, "client", current)
    tracing.configure(settings())
    assert tracing.client() is current


def test_an_unconfigured_process_gets_one_no_op_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing._state, "client", None)
    first = tracing.client()
    with first.start_as_current_observation(name="read-pdf"):
        assert first.get_current_trace_id() is None
    assert tracing.client() is first


def test_shutdown_before_first_use_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing._state, "client", None)
    tracing.shutdown()


# T-TR-2 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({}, {}),
        ({"prompt": 10, "completion": 4}, {"input": 10, "output": 4}),
        (
            {"prompt": 10, "completion": 4, "cached": 6},
            {"input": 4, "input_cached_tokens": 6, "output": 4},
        ),
        (
            {"prompt": 10, "completion": 4, "reasoning": 3},
            {"input": 10, "output": 1, "output_reasoning_tokens": 3},
        ),
        ({"prompt": 10, "completion": 4, "cached": 0, "reasoning": 0}, {"input": 10, "output": 4}),
        (
            {"prompt": 10, "completion": 4, "cached": 12, "reasoning": 9},
            {"input": 0, "input_cached_tokens": 10, "output": 0, "output_reasoning_tokens": 4},
        ),
        ({"completion": 4, "cached": 3}, {"output": 4}),
        ({"prompt": 7, "reasoning": 2}, {"input": 7}),
    ],
)
def test_usage_details_are_exclusive_buckets(
    counts: dict[str, int], expected: dict[str, int]
) -> None:
    assert tracing.usage_details(**counts) == expected


@pytest.mark.parametrize(("cost", "expected"), [(0.0, {"total": 0.0}), (0.0012, {"total": 0.0012})])
def test_a_reported_cost_is_the_total(cost: float, expected: dict[str, float]) -> None:
    assert tracing.cost_details(cost) == expected


def test_no_cost_is_no_cost_details() -> None:
    assert tracing.cost_details(None) is None


# T-TR-3 ----------------------------------------------------------------------------------------


def emit(traces: Traces, tags: list[str] | None) -> None:
    """A small job-shaped trace whose input, output and metadata hold document text."""
    client = traces.client
    with (
        client.start_as_current_observation(
            as_type="chain",
            name="build-document-graph",
            input={"kind": "upload", "file_name": "acme-fees.pdf"},
        ) as root,
        propagate_attributes(
            trace_name="build-document-graph",
            session_id="dossier-1",
            tags=tags,
            metadata={"job_id": "j-1", "document_id": "d-1", "title": SECRET},
        ),
    ):
        with client.start_as_current_observation(
            as_type="generation",
            name="classify",
            model="m/primary:free",
            input=[{"role": "user", "content": SECRET}],
            metadata={"task": "classify", "attempt": 1, "quote": SECRET},
        ) as gen:
            gen.update(
                output={"role": "assistant", "content": SECRET, "reasoning": SECRET},
                usage_details={"input": 3, "output": 2},
                level="WARNING",
                status_message="no_json",
            )
        root.update(output={"status": "succeeded", "title": SECRET})


@pytest.mark.parametrize("tags", [["inkthread", "kind:upload"], None, ["inkthread"]])
def test_spans_not_tagged_as_a_sample_export_no_document_text(
    traces: Traces, tags: list[str] | None
) -> None:
    emit(traces, tags)
    spans = traces.spans()
    assert [s.name for s in spans] == ["build-document-graph", "classify"]
    for span in spans:
        assert traces.attr(span, INPUT) is None
        assert traces.attr(span, OUTPUT) is None
        assert SECRET not in traces.everything(span)
        assert "acme-fees.pdf" not in traces.everything(span)
        assert traces.metadata(span)["withheld"] == "uploads keep no document text (DR-0029)"
        assert traces.attr(span, "langfuse.trace.name") == "build-document-graph"
        assert traces.attr(span, "session.id") == "dossier-1"
        assert traces.attr(span, "langfuse.environment") == "test"
        assert traces.attr(span, "langfuse.trace.metadata.job_id") == '"j-1"'
        assert traces.attr(span, "langfuse.trace.metadata.title") is None
    gen = traces.one("classify")
    assert traces.metadata(gen) == {
        "task": "classify",
        "attempt": 1,
        "withheld": "uploads keep no document text (DR-0029)",
    }
    assert traces.attr(gen, "langfuse.observation.model.name") == "m/primary:free"
    assert traces.decoded(gen, "langfuse.observation.usage_details") == {"input": 3, "output": 2}
    assert traces.level(gen) == "WARNING"
    assert traces.status_message(gen) == "no_json"


def test_a_samples_spans_keep_their_text(traces: Traces) -> None:
    emit(traces, ["inkthread", "kind:sample"])
    gen = traces.one("classify")
    assert traces.decoded(gen, INPUT) == [{"role": "user", "content": SECRET}]
    assert traces.decoded(gen, OUTPUT)["content"] == SECRET
    assert traces.metadata(gen)["quote"] == SECRET
    assert "withheld" not in traces.metadata(gen)
    root = traces.one("build-document-graph")
    assert traces.decoded(root, INPUT) == {"kind": "upload", "file_name": "acme-fees.pdf"}


# T-TR-4 ----------------------------------------------------------------------------------------


def test_a_failing_step_records_only_the_exceptions_type(traces: Traces) -> None:
    boom = ValueError(f"cannot place '{SECRET}'")
    with (
        pytest.raises(ValueError, match="cannot place") as caught,
        tracing.step("finalize-graph", as_type="chain"),
    ):
        raise boom
    assert caught.value is boom
    span = traces.one("finalize-graph")
    assert traces.level(span) == "ERROR"
    assert traces.status_message(span) == "ValueError"
    assert span.events == ()
    assert SECRET not in traces.everything(span)


async def test_a_cancelled_step_is_an_error(traces: Traces) -> None:
    async def body() -> None:
        with tracing.step("relate-parts", as_type="agent"):
            await asyncio.sleep(10)

    task = asyncio.create_task(body())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    span = traces.one("relate-parts")
    assert traces.level(span) == "ERROR"
    assert traces.status_message(span) == "cancelled"


def test_steps_nest_and_carry_their_type(traces: Traces) -> None:
    with (
        tracing.job_trace(
            job_id=uuid.uuid4(), document_id=uuid.uuid4(), kind="sample", file_name="a.pdf"
        ),
        tracing.step("verify-claims", as_type="evaluator", metadata={"stage": "verify_agent"}),
    ):
        pass
    root, verify = traces.one("build-document-graph"), traces.one("verify-claims")
    assert traces.parent(verify) == root
    assert traces.type_of(root) == "chain"
    assert traces.type_of(verify) == "evaluator"
    assert traces.metadata(verify) == {"stage": "verify_agent"}
