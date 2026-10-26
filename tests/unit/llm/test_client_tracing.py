"""Spec 14 § 2 generations: one per HTTP attempt, over a mocked OpenRouter (T-TR-5..7).

Attempts run as a sample's (`as_sample`) where a test reads their input, output or metadata: any
other span loses those at export (spec 14 § 3).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager

import httpx
import pytest
import respx
from fake_llm import CountingBudget
from langfuse import propagate_attributes
from tracing_support import INPUT, OUTPUT, Traces

from inkthread.llm.catalog import ModelCatalog
from inkthread.llm.client import OpenRouterModel
from inkthread.llm.ports import Message, ModelAuthFailed, ModelRequest

BASE = "https://openrouter.test/api/v1"
PRIMARY = "p/primary:free"
FALLBACK = "f/fallback:free"
NONE = "n/none:free"
SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"labels": {"type": "array"}},
    "required": ["labels"],
    "additionalProperties": False,
}
ANSWER = '{"labels": []}'
CATALOG = {
    "data": [
        {"id": PRIMARY, "supported_parameters": ["structured_outputs", "response_format"]},
        {"id": FALLBACK, "supported_parameters": ["response_format", "temperature"]},
        {"id": NONE, "supported_parameters": ["temperature"]},
    ]
}
MESSAGES = [{"role": "system", "content": "Label."}, {"role": "user", "content": "{}"}]


def reply(content: str | None, *, finish: str = "stop", **extra: object) -> httpx.Response:
    body: dict[str, object] = {
        "id": "gen-1",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    body.update(extra)
    return httpx.Response(200, json=body)


def request(cascade: tuple[str, ...] = (PRIMARY, FALLBACK)) -> ModelRequest:
    return ModelRequest(
        task="classify",
        messages=(Message(role="system", content="Label."), Message(role="user", content="{}")),
        schema=SCHEMA,
        temperature=0.0,
        max_tokens=500,
        cascade=cascade,
    )


async def no_sleep(_seconds: float) -> None:
    return None


def as_sample() -> AbstractContextManager[object]:
    return propagate_attributes(tags=["inkthread", "kind:sample"])


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


def model(http: httpx.AsyncClient) -> OpenRouterModel:
    return OpenRouterModel(
        api_key="sk-or-secret",
        base_url=BASE,
        site_url="https://inkthread.test",
        app_name="inkthread",
        http=http,
        catalog=ModelCatalog(http, BASE),
        max_tokens=6000,
        timeout_s=90,
        sleep=no_sleep,
        budget=CountingBudget(),
    )


def catalog() -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))


@respx.mock
async def test_each_attempt_is_a_generation(traces: Traces, http: httpx.AsyncClient) -> None:
    catalog()
    usage = {
        "prompt_tokens": 12,
        "completion_tokens": 6,
        "total_tokens": 18,
        "cost": 0,
        "prompt_tokens_details": {"cached_tokens": 3},
        "completion_tokens_details": {"reasoning_tokens": 2},
    }
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(429), reply(ANSWER, usage=usage, provider="Nvidia")]
    )
    with as_sample():
        result = await model(http).complete(request())
    assert result.served_model == PRIMARY
    first, second = traces.named("classify")
    assert traces.type_of(first) == "generation"
    assert traces.level(first) == "ERROR"
    assert traces.status_message(first) == "http_error: status=429"
    assert traces.attr(first, "langfuse.observation.model.name") == PRIMARY
    assert traces.metadata(first) == {"task": "classify", "attempt": 1}
    assert traces.level(second) == "DEFAULT"
    assert traces.decoded(second, INPUT) == MESSAGES
    assert traces.decoded(second, OUTPUT) == {"role": "assistant", "content": ANSWER}
    assert traces.decoded(second, "langfuse.observation.usage_details") == {
        "input": 9,
        "input_cached_tokens": 3,
        "output": 4,
        "output_reasoning_tokens": 2,
    }
    assert traces.decoded(second, "langfuse.observation.cost_details") == {"total": 0.0}
    assert traces.decoded(second, "langfuse.observation.model.parameters") == {
        "temperature": 0.0,
        "max_tokens": 500,
        "response_format": "json_schema",
        "reasoning_effort": "low",
    }
    assert traces.metadata(second) == {"task": "classify", "attempt": 2, "provider": "Nvidia"}


@respx.mock
@pytest.mark.parametrize(
    ("cascade", "expected"),
    [((FALLBACK,), "json_object"), ((NONE,), "none")],
)
async def test_the_response_format_is_a_model_parameter(
    traces: Traces, http: httpx.AsyncClient, cascade: tuple[str, ...], expected: str
) -> None:
    catalog()
    respx.post(f"{BASE}/chat/completions").mock(return_value=reply(ANSWER))
    await model(http).complete(request(cascade))
    params = traces.decoded(traces.one("classify"), "langfuse.observation.model.parameters")
    assert params["response_format"] == expected


@respx.mock
@pytest.mark.parametrize(
    ("first", "status"),
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "transport_error"),
        (httpx.Response(503), "http_error: status=503"),
        (reply(ANSWER, finish="length"), "length"),
        (reply(""), "empty"),
        (reply(None), "empty"),
        (httpx.Response(200, text="<html>"), "bad_response"),
    ],
)
async def test_a_failed_attempt_is_an_error_with_its_status(
    traces: Traces, http: httpx.AsyncClient, first: httpx.Response | Exception, status: str
) -> None:
    catalog()
    respx.post(f"{BASE}/chat/completions").mock(side_effect=[first, reply(ANSWER)])
    await model(http).complete(request())
    failed, answered = traces.named("classify")
    assert traces.level(failed) == "ERROR"
    assert traces.status_message(failed) == status
    assert traces.level(answered) == "DEFAULT"


@respx.mock
async def test_a_reply_without_json_keeps_its_text(traces: Traces, http: httpx.AsyncClient) -> None:
    catalog()
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[reply("I cannot help with that."), reply(ANSWER)]
    )
    with as_sample():
        await model(http).complete(request())
    failed = traces.named("classify")[0]
    assert traces.status_message(failed) == "no_json"
    assert traces.decoded(failed, OUTPUT) == {
        "role": "assistant",
        "content": "I cannot help with that.",
    }


@respx.mock
async def test_401_is_one_error_generation(traces: Traces, http: httpx.AsyncClient) -> None:
    catalog()
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401))
    with pytest.raises(ModelAuthFailed):
        await model(http).complete(request())
    (failed,) = traces.named("classify")
    assert traces.status_message(failed) == "http_error: status=401"
    assert "sk-or-secret" not in traces.everything(failed)


@respx.mock
async def test_an_attempt_cut_off_is_cancelled(traces: Traces, http: httpx.AsyncClient) -> None:
    catalog()

    started = asyncio.Event()

    async def hang(_request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(10)
        return reply(ANSWER)  # pragma: no cover

    respx.post(f"{BASE}/chat/completions").mock(side_effect=hang)
    task = asyncio.create_task(model(http).complete(request()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (cut,) = traces.named("classify")
    assert traces.level(cut) == "ERROR"
    assert traces.status_message(cut) == "cancelled"


@respx.mock
async def test_reasoning_is_kept_on_the_output(traces: Traces, http: httpx.AsyncClient) -> None:
    catalog()
    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": ANSWER, "reasoning": "first, think"},
                "finish_reason": "stop",
            }
        ]
    }
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(200, json=body))
    with as_sample():
        await model(http).complete(request())
    assert traces.decoded(traces.one("classify"), OUTPUT) == {
        "role": "assistant",
        "content": ANSWER,
        "reasoning": "first, think",
    }


@respx.mock
@pytest.mark.parametrize(
    ("usage", "buckets"),
    [
        ('{"prompt_tokens": "10", "completion_tokens": 4.5, "cost": "0.1"}', None),
        ('{"prompt_tokens": -3, "completion_tokens": true, "cost": true}', None),
        ('{"prompt_tokens": null, "completion_tokens": 4, "cost": NaN}', {"output": 4}),
        ('{"prompt_tokens": 5, "cost": Infinity, "prompt_tokens_details": "x"}', {"input": 5}),
        ('"not-an-object"', None),
        ("[1, 2]", None),
    ],
)
async def test_unreadable_usage_never_fails_the_attempt(
    traces: Traces, http: httpx.AsyncClient, usage: str, buckets: dict[str, int] | None
) -> None:
    catalog()
    content = json.dumps({"choices": [{"message": {"content": ANSWER}, "finish_reason": "stop"}]})
    body = content[:-1] + ', "usage": ' + usage + "}"
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, content=body.encode())
    )
    result = await model(http).complete(request())
    assert result.served_model == PRIMARY
    gen = traces.one("classify")
    assert traces.level(gen) == "DEFAULT"
    assert traces.decoded(gen, "langfuse.observation.usage_details") == buckets
    assert traces.decoded(gen, "langfuse.observation.cost_details") is None
