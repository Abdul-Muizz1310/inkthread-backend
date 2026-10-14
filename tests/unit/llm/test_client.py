"""Spec 05 § 6 transport over a mocked OpenRouter (T-AG-17..22b)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from fake_llm import CountingBudget

from inkthread.llm.catalog import ModelCatalog
from inkthread.llm.client import OpenRouterModel
from inkthread.llm.ports import (
    BudgetExhausted,
    Message,
    ModelAuthFailed,
    ModelRequest,
    ModelUnavailable,
)

BASE = "https://openrouter.test/api/v1"
PRIMARY = "p/primary:free"
FALLBACK = "f/fallback:free"
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
        {"id": "n/none:free", "supported_parameters": ["temperature"]},
    ]
}


def reply(content: str | None, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "gen-1",
            "model": "whatever",
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        },
    )


def request(cascade: tuple[str, ...] = (PRIMARY, FALLBACK)) -> ModelRequest:
    return ModelRequest(
        task="classify",
        messages=(Message(role="system", content="Label."), Message(role="user", content="{}")),
        schema=SCHEMA,
        temperature=0.0,
        max_tokens=500,
        cascade=cascade,
    )


class Sleeps:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


def model(
    http: httpx.AsyncClient, budget: CountingBudget | None = None, sleeps: Sleeps | None = None
) -> OpenRouterModel:
    return OpenRouterModel(
        api_key="sk-or-secret",
        base_url=BASE,
        site_url="https://inkthread.test",
        app_name="inkthread",
        http=http,
        catalog=ModelCatalog(http, BASE),
        max_tokens=6000,
        timeout_s=90,
        sleep=sleeps or Sleeps(),
        budget=budget or CountingBudget(),
    )


def bodies(route: respx.Route) -> list[dict[str, object]]:
    return [json.loads(c.request.content) for c in route.calls]


@respx.mock
async def test_429_then_200_succeeds_on_second_attempt(http: httpx.AsyncClient) -> None:  # T-AG-17
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(429), reply(ANSWER)]
    )
    sleeps = Sleeps()
    budget = CountingBudget()
    result = await model(http, budget, sleeps).complete(request())
    assert result.served_model == PRIMARY
    assert json.loads(result.text) == {"labels": []}
    assert [a.http_status for a in result.attempts] == [429, 200]
    assert [a.status for a in result.attempts] == ["http_error", "ok"]
    assert result.usage.prompt_tokens == 12
    assert budget.spent() == 2
    assert len(sleeps.calls) == 1
    assert 1.5 <= sleeps.calls[0] <= 2.5
    assert {b["model"] for b in bodies(route)} == {PRIMARY}


@respx.mock
async def test_500_twice_falls_back(http: httpx.AsyncClient) -> None:  # T-AG-18
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(500), httpx.Response(502), reply(ANSWER)]
    )
    result = await model(http).complete(request())
    assert result.served_model == FALLBACK
    assert [b["model"] for b in bodies(route)] == [PRIMARY, PRIMARY, FALLBACK]


@respx.mock
async def test_400_goes_straight_to_fallback(http: httpx.AsyncClient) -> None:  # T-AG-19
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(400, json={"error": {"message": "bad"}}), reply(ANSWER)]
    )
    sleeps = Sleeps()
    result = await model(http, sleeps=sleeps).complete(request())
    assert result.served_model == FALLBACK
    assert [b["model"] for b in bodies(route)] == [PRIMARY, FALLBACK]
    assert sleeps.calls == []


@respx.mock
async def test_401_stops_the_cascade(http: httpx.AsyncClient) -> None:  # T-AG-20
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(401))
    with pytest.raises(ModelAuthFailed) as info:
        await model(http).complete(request())
    assert route.call_count == 1
    assert len(info.value.attempts) == 1
    assert "sk-or-secret" not in str(info.value)


@respx.mock
@pytest.mark.parametrize("bad", [reply(ANSWER, finish="length"), reply(""), reply(None)])
async def test_length_and_empty_content_are_failed_attempts(
    http: httpx.AsyncClient, bad: httpx.Response
) -> None:  # T-AG-21
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(side_effect=[bad, reply(ANSWER)])
    result = await model(http).complete(request())
    assert route.call_count == 2
    assert result.attempts[0].status in {"length", "empty"}
    assert result.served_model == PRIMARY


@respx.mock
async def test_every_attempt_failing_is_unavailable(http: httpx.AsyncClient) -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(503))
    with pytest.raises(ModelUnavailable) as info:
        await model(http).complete(request())
    assert route.call_count == 4
    assert len(info.value.attempts) == 4


@respx.mock
async def test_timeouts_retry_then_fall_back(http: httpx.AsyncClient) -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), reply(ANSWER)]
    )
    result = await model(http).complete(request())
    assert result.served_model == FALLBACK
    assert [a.status for a in result.attempts] == ["timeout", "timeout", "ok"]


@respx.mock
async def test_budget_is_checked_before_every_attempt(http: httpx.AsyncClient) -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(500))
    with pytest.raises(BudgetExhausted) as info:
        await model(http, CountingBudget(limit=1)).complete(request())
    assert route.call_count == 1
    assert len(info.value.attempts) == 1


@respx.mock
async def test_deadline_ends_the_cascade(http: httpx.AsyncClient) -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(500))
    ticks = iter([0.0, 0.0, 200.0, 200.0, 200.0])
    client = model(http)
    client.clock = lambda: next(ticks)
    with pytest.raises(ModelUnavailable):
        await client.complete(request())
    assert route.call_count == 1


@respx.mock
async def test_response_format_follows_the_catalogue(http: httpx.AsyncClient) -> None:  # T-AG-22
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(400), reply(ANSWER)]
    )
    await model(http).complete(request())
    first, second = bodies(route)
    assert first["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "classify", "strict": True, "schema": SCHEMA},
    }
    assert first["reasoning"] == {"effort": "low"}
    assert first["max_tokens"] == 500
    assert first["temperature"] == 0.0
    assert second["response_format"] == {"type": "json_object"}
    system = second["messages"][0]  # type: ignore[index]
    assert '"additionalProperties":false' in system["content"]
    headers = route.calls[0].request.headers
    assert headers["authorization"] == "Bearer sk-or-secret"
    assert headers["http-referer"] == "https://inkthread.test"
    assert headers["x-title"] == "inkthread"


@respx.mock
async def test_no_format_support_puts_schema_in_prompt(http: httpx.AsyncClient) -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply(ANSWER))
    await model(http).complete(request(("n/none:free",)))
    (body,) = bodies(route)
    assert "response_format" not in body
    assert '"labels"' in body["messages"][0]["content"]  # type: ignore[index]


@respx.mock
@pytest.mark.parametrize(
    "content",
    [
        'Sure! Here it is: {"labels": []} Hope that helps.',
        '```json\n{"labels": []}\n```',
        'Thinking {not json} then {"labels": []}',
    ],
)
async def test_json_is_extracted_from_prose_and_fences(
    http: httpx.AsyncClient, content: str
) -> None:  # T-AG-22b
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    respx.post(f"{BASE}/chat/completions").mock(return_value=reply(content))
    result = await model(http).complete(request())
    assert json.loads(result.text) == {"labels": []}


@respx.mock
async def test_reply_without_json_is_a_failed_attempt(http: httpx.AsyncClient) -> None:  # T-AG-22b
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=CATALOG))
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[reply("I cannot help with that."), reply(ANSWER)]
    )
    result = await model(http).complete(request())
    assert route.call_count == 2
    assert result.attempts[0].status == "no_json"
