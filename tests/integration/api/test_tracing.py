"""Spec 14 composed cases: a job's trace through the real runner and OpenRouter client (T-TR-9..15).

Postgres via Testcontainers, the in-process reader, `OpenRouterModel` over respx, and the spans read
from an in-memory exporter that carries the production upload mask.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import httpx
import pdfs
import pytest
import respx
from apiharness import Api, ApiFactory
from fake_llm import CountingBudget
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from tracing_support import INPUT, OUTPUT, Traces, tracing_client

from inkthread.core import tracing
from inkthread.core.config import Settings
from inkthread.llm.catalog import ModelCatalog
from inkthread.llm.client import OpenRouterModel
from inkthread.reader.process import ReadFailure, ReadOutcome

pytestmark = pytest.mark.integration

BASE = "https://openrouter.test/api/v1"
PRIMARY, FAST, FALLBACK = "p/primary:free", "v/fast:free", "f/fallback:free"
FILE_NAME = "acme-confidential-fees.pdf"
DOCUMENT_WORDS = (
    pdfs.SECTIONED_TITLE,
    "These rules govern",
    "admitted to trade",
    "schedule below",
    FILE_NAME,
)
STAGES = [
    ("read-pdf", "chain"),
    ("build-structure", "chain"),
    ("classify-by-rules", "chain"),
    ("classify-parts", "agent"),
    ("link-by-rules", "chain"),
    ("relate-parts", "agent"),
    ("verify-claims", "evaluator"),
    ("finalize-graph", "chain"),
]


def _answer(request: httpx.Request) -> httpx.Response:
    """Each task's answer, made from its own payload: grounded labels, no relations, support."""
    body = json.loads(request.content)
    task = body["response_format"]["json_schema"]["name"]
    data = json.loads(body["messages"][-1]["content"].split("\n", 1)[1])
    if task == "classify":
        labels = [
            {
                "part": part["id"],
                "roles": ["condition"],
                "evidence": [{"role": "condition", "quote": " ".join(part["text"].split()[:4])}],
            }
            for part in data["parts"]
        ]
        content = json.dumps({"labels": labels})
    elif task == "relate":
        content = json.dumps({"relations": []})
    else:
        verdicts = [{"claim": c["id"], "verdict": "supported"} for c in data["claims"]]
        content = json.dumps({"verdicts": verdicts})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 8, "cost": 0},
            "provider": "Stub",
        },
    )


@pytest.fixture
async def openrouter() -> AsyncIterator[OpenRouterModel]:
    supported = ["structured_outputs", "response_format"]
    catalog = {"data": [{"id": m, "supported_parameters": supported} for m in (PRIMARY, FAST)]}
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=catalog))
        mock.post(f"{BASE}/chat/completions").mock(side_effect=_answer)
        mock.route(host="test").pass_through()
        async with httpx.AsyncClient() as http:
            yield OpenRouterModel(
                api_key="sk-or-test",
                base_url=BASE,
                site_url="https://inkthread.test",
                app_name="inkthread",
                http=http,
                catalog=ModelCatalog(http, BASE),
                budget=CountingBudget(),
            )


@pytest.fixture
def live(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        llm_mode="live",
        sample_llm_mode="live",
        openrouter_api_key="sk-or-test",
        openrouter_base_url=BASE,
        openrouter_model_primary=PRIMARY,
        openrouter_model_fast=FAST,
        openrouter_model_fallback=FALLBACK,
    )


async def _upload(a: Api, headers: dict[str, str]) -> dict[str, Any]:
    files = {"file": (FILE_NAME, pdfs.sectioned(), "application/pdf")}
    r = await a.client.post("/documents", files=files, headers=headers)
    assert r.status_code == 202, r.text
    return await a.wait_job(r.json()["job"]["id"])


def _trace_wide(traces: Traces, spans: Sequence[ReadableSpan], key: str) -> set[Any]:
    return {traces.attr(s, key) for s in spans}


async def test_T_TR_9_a_job_is_one_trace_shaped_like_the_run(
    api: ApiFactory, live: Settings, openrouter: OpenRouterModel, traces: Traces
) -> None:
    async with api(run_jobs=True, settings=live, model=openrouter) as a:
        job = await _upload(a, {"X-Request-Id": "dossier-9"})
        assert job["status"] == "succeeded", job
        spans = traces.spans()

    assert len({s.context.trace_id for s in spans}) == 1
    root = traces.one("build-document-graph")
    assert traces.parent(root) is None
    assert traces.type_of(root) == "chain"
    stages = traces.children(root)
    assert [(s.name, traces.type_of(s)) for s in stages] == STAGES
    by_name = {s.name: s for s in stages}
    for stage, task in (
        ("classify-parts", "classify"),
        ("relate-parts", "relate"),
        ("verify-claims", "verify"),
    ):
        kids = traces.children(by_name[stage])
        assert [(k.name, traces.type_of(k)) for k in kids] == [
            ("recall-answer", "retriever"),
            (task, "generation"),
        ], stage
        assert traces.metadata(kids[1])["provider"] == "Stub"
    assert traces.metadata(by_name["read-pdf"])["status"] == "completed"
    assert traces.level(root) == "DEFAULT"
    outcome = traces.metadata(root)
    assert outcome["status"] == "succeeded"
    assert outcome["nodes"] > 0
    assert outcome["edges"] > 0

    assert _trace_wide(traces, spans, "langfuse.trace.name") == {"build-document-graph"}
    assert _trace_wide(traces, spans, "langfuse.trace.tags") == {("inkthread", "kind:upload")}
    assert _trace_wide(traces, spans, "langfuse.environment") == {"test"}
    assert _trace_wide(traces, spans, "session.id") == {"dossier-9"}
    assert _trace_wide(traces, spans, "langfuse.trace.metadata.job_id") == {json.dumps(job["id"])}
    assert _trace_wide(traces, spans, "langfuse.trace.metadata.document_id") == {
        json.dumps(job["document_id"])
    }

    # T-TR-10: none of the upload's words left the process.
    for span in spans:
        assert traces.attr(span, INPUT) is None, span.name
        assert traces.attr(span, OUTPUT) is None, span.name
        exported = traces.everything(span)
        for word in DOCUMENT_WORDS:
            assert word not in exported, (span.name, word)


async def test_T_TR_11_a_sample_keeps_its_input_and_output(
    api: ApiFactory, live: Settings, openrouter: OpenRouterModel, traces: Traces
) -> None:
    async with api(run_jobs=True, settings=live, model=openrouter) as a:
        out = await a.app.state.services.ingest.ingest(
            pdfs.sectioned(), "sample-fees.pdf", kind="sample"
        )
        assert out.job is not None
        job = await a.wait_job(str(out.job.id))
        assert job["status"] == "succeeded", job
        spans = traces.spans()

    assert _trace_wide(traces, spans, "langfuse.trace.tags") == {("inkthread", "kind:sample")}
    root = traces.one("build-document-graph")
    assert traces.decoded(root, INPUT) == {"kind": "sample", "file_name": "sample-fees.pdf"}
    output = traces.decoded(root, OUTPUT)
    assert output["status"] == "succeeded"
    assert output["graph_hash"]
    classify = traces.one("classify")
    prompt = json.dumps(traces.decoded(classify, INPUT))
    assert "These rules govern" in prompt
    assert "labels" in traces.decoded(classify, OUTPUT)["content"]


async def test_T_TR_12_no_request_id_no_session(
    api: ApiFactory, live: Settings, openrouter: OpenRouterModel, traces: Traces
) -> None:
    async with api(run_jobs=True, settings=live, model=openrouter) as a:
        job = await _upload(a, {})
        assert job["status"] == "succeeded", job
        spans = traces.spans()
    assert spans
    assert _trace_wide(traces, spans, "session.id") == {None}


async def _refuse(_pdf: bytes) -> ReadOutcome:
    return ReadFailure(code="pdf_unreadable", message="the bytes are not a PDF the reader can open")


async def test_T_TR_13_a_refused_pdf_is_an_error_trace(
    api: ApiFactory, live: Settings, openrouter: OpenRouterModel, traces: Traces
) -> None:
    async with api(run_jobs=True, settings=live, model=openrouter, reader=_refuse) as a:
        job = await _upload(a, {})
        assert job["status"] == "failed"
        assert job["error"]["code"] == "pdf_unreadable"
        spans = traces.spans()
    read, root = traces.one("read-pdf"), traces.one("build-document-graph")
    assert (traces.level(read), traces.status_message(read)) == ("ERROR", "pdf_unreadable")
    assert (traces.level(root), traces.status_message(root)) == ("ERROR", "pdf_unreadable")
    assert [s.name for s in traces.children(root)] == ["read-pdf"]
    assert len(spans) == 2


class _BrokenExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        msg = "langfuse is down"
        raise RuntimeError(msg)

    def shutdown(self) -> None:
        return None


async def test_T_TR_14_an_exporter_failure_never_changes_the_job(
    api: ApiFactory,
    live: Settings,
    openrouter: OpenRouterModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = tracing_client(_BrokenExporter())
    monkeypatch.setattr(tracing._state, "client", client)
    async with api(run_jobs=True, settings=live, model=openrouter) as a:
        job = await _upload(a, {})
        client.flush()
    assert job["status"] == "succeeded", job


async def test_T_TR_15_the_lifespan_ends_with_one_shutdown(
    api: ApiFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(tracing, "shutdown", lambda: calls.append("shutdown"))
    async with api():
        assert calls == []
    assert calls == ["shutdown"]
