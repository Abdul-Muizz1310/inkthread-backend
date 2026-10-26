"""OpenRouter chat completions with a cascade, retries and a budget (spec 05 § 6).

Every HTTP attempt is one Langfuse generation named after the task (spec 14 § 2).
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

import httpx
import structlog
from langfuse import LangfuseGeneration
from langfuse.api import MapValue
from pydantic import BaseModel, BeforeValidator, SecretStr, ValidationError

from inkthread.canon import cjson
from inkthread.core import tracing
from inkthread.llm.catalog import ModelCatalog
from inkthread.llm.ports import (
    Attempt,
    AttemptStatus,
    BudgetExhausted,
    BudgetPort,
    ModelAuthFailed,
    ModelRequest,
    ModelResult,
    ModelUnavailable,
    Usage,
)

_log = structlog.get_logger(__name__)

ATTEMPTS_PER_MODEL = 2
BACKOFF_S = (2.0, 4.0)
JITTER = 0.25
DEADLINE_S = 180.0
REASONING_EFFORT = "low"
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _count(value: object) -> int | None:
    """A token count as reported, or None unless it is a non-negative integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _cost(value: object) -> float | None:
    """A cost as reported, or None unless it is a finite, non-negative number."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    cost = float(value)
    return cost if math.isfinite(cost) and cost >= 0 else None


def _mapping_or_none(value: object) -> object:
    return value if isinstance(value, Mapping) else None


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


Count = Annotated[int | None, BeforeValidator(_count)]
Cost = Annotated[float | None, BeforeValidator(_cost)]
Text = Annotated[str | None, BeforeValidator(_text_or_none)]


class _ChatMessage(BaseModel):
    content: str | None = None
    reasoning: Text = None


class _Choice(BaseModel):
    message: _ChatMessage
    finish_reason: str | None = None


class _Details(BaseModel):
    cached_tokens: Count = None
    reasoning_tokens: Count = None


class _Usage(BaseModel):
    """Telemetry: a field that does not read is dropped, never a failed attempt."""

    prompt_tokens: Count = None
    completion_tokens: Count = None
    cost: Cost = None
    prompt_tokens_details: Annotated[_Details | None, BeforeValidator(_mapping_or_none)] = None
    completion_tokens_details: Annotated[_Details | None, BeforeValidator(_mapping_or_none)] = None


class _ReplyError(BaseModel):
    code: Count = None


class _ErrorReply(BaseModel):
    """OpenRouter's error object, which can come back inside a 200 instead of a completion."""

    error: Annotated[_ReplyError | None, BeforeValidator(_mapping_or_none)] = None


def upstream_error_code(content: bytes) -> int | None:
    """The status code of an OpenRouter error object in a 200's body, if the body is one."""
    try:
        reply = _ErrorReply.model_validate_json(content)
    except ValidationError:
        return None
    return reply.error.code if reply.error else None


class _ChatResponse(BaseModel):
    choices: list[_Choice]
    usage: Annotated[_Usage | None, BeforeValidator(_mapping_or_none)] = None
    provider: Text = None


def extract_json_object(text: str) -> str | None:
    """The first JSON object in a reply (bare, fenced or wrapped in prose), re-serialised."""
    candidates = [text.strip(), *(m.group(1).strip() for m in _FENCE.finditer(text))]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate, start)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return json.dumps(value, ensure_ascii=False)
    return None


@dataclass(frozen=True)
class _Outcome:
    """One attempt's facts, and what the model sent back (for the trace) when it answered."""

    attempt: Attempt
    retry: bool
    result: ModelResult | None = None
    reply: _ChatResponse | None = None


ResponseFormat = Literal["json_schema", "json_object", "none"]


@dataclass(frozen=True)
class _Prepared:
    """One model's request body and the trace's view of it."""

    body: dict[str, object]
    messages: list[dict[str, str]]
    parameters: dict[str, MapValue]


class OpenRouterModel:
    """`ModelPort` over OpenRouter: each model gets two attempts, then the cascade moves on."""

    def __init__(
        self,
        *,
        api_key: SecretStr | str,
        base_url: str,
        site_url: str,
        app_name: str,
        http: httpx.AsyncClient,
        catalog: ModelCatalog,
        budget: BudgetPort,
        max_tokens: int = 12000,
        timeout_s: float = 90.0,
        deadline_s: float = DEADLINE_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._site_url = site_url
        self._app_name = app_name
        self._http = http
        self._catalog = catalog
        self._budget = budget
        self._max_tokens = max_tokens
        self._timeout = timeout_s
        self._deadline = deadline_s
        self._sleep = sleep
        self.clock: Callable[[], float] = time.monotonic
        self.jitter: Callable[[], float] = random.random

    async def complete(self, req: ModelRequest) -> ModelResult:
        """Walk the cascade until a model gives a JSON object; raise a `ModelError` otherwise."""
        started = self.clock()
        attempts: list[Attempt] = []
        for slug in req.cascade:
            prepared = await self._body(req, slug)
            for n in range(ATTEMPTS_PER_MODEL):
                remaining = self._deadline - (self.clock() - started)
                if remaining <= 0:
                    raise ModelUnavailable(attempts, "the cascade deadline passed")
                if not await self._budget.acquire():
                    raise BudgetExhausted(attempts, "the request budget is spent")
                outcome = await self._traced(
                    req, slug, prepared, min(self._timeout, remaining), attempt=n + 1
                )
                attempts.append(outcome.attempt)
                if outcome.result is not None:
                    return ModelResult(
                        text=outcome.result.text,
                        served_model=slug,
                        finish_reason=outcome.result.finish_reason,
                        usage=outcome.result.usage,
                        attempts=tuple(attempts),
                    )
                if outcome.attempt.http_status == 401:
                    raise ModelAuthFailed(attempts, "the provider refused the API key")
                if not outcome.retry:
                    break
                if n + 1 < ATTEMPTS_PER_MODEL:
                    base = BACKOFF_S[min(n, len(BACKOFF_S) - 1)]
                    await self._sleep(base * (1 + JITTER * (2 * self.jitter() - 1)))
        raise ModelUnavailable(attempts, "every model in the cascade failed")

    async def _body(self, req: ModelRequest, slug: str) -> _Prepared:
        caps = await self._catalog.capabilities(slug)
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        max_tokens = req.max_tokens or self._max_tokens
        body: dict[str, object] = {
            "model": slug,
            "temperature": req.temperature,
            "max_tokens": max_tokens,
            "reasoning": {"effort": REASONING_EFFORT},
        }
        response_format: ResponseFormat = "none"
        if caps.structured_outputs:
            response_format = "json_schema"
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": req.task, "strict": True, "schema": dict(req.schema)},
            }
        else:
            messages = _with_schema(messages, req)
            if caps.response_format:
                response_format = "json_object"
                body["response_format"] = {"type": "json_object"}
        body["messages"] = messages
        parameters: dict[str, MapValue] = {
            "temperature": req.temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "reasoning_effort": REASONING_EFFORT,
        }
        return _Prepared(body=body, messages=messages, parameters=parameters)

    async def _traced(
        self, req: ModelRequest, slug: str, prepared: _Prepared, timeout: float, *, attempt: int
    ) -> _Outcome:
        """One attempt inside its generation (spec 14 § 2)."""
        with tracing.generation(
            req.task,
            model=slug,
            messages=prepared.messages,
            parameters=prepared.parameters,
            metadata={"task": req.task, "attempt": attempt},
        ) as observed:
            outcome = await self._attempt(slug, prepared.body, timeout)
            _record(observed, outcome)
        return outcome

    async def _attempt(self, slug: str, body: dict[str, object], timeout: float) -> _Outcome:
        headers = {
            "Authorization": f"Bearer {self._key.get_secret_value()}",
            "HTTP-Referer": self._site_url,
            "X-Title": self._app_name,
        }
        start = self.clock()

        def attempt(
            status: AttemptStatus, http_status: int | None, usage: Usage | None = None
        ) -> Attempt:
            return Attempt(
                model=slug,
                status=status,
                http_status=http_status,
                latency_ms=max(0, round((self.clock() - start) * 1000)),
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
            )

        try:
            response = await self._http.post(self._url, json=body, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            return _Outcome(attempt("timeout", None), retry=True)
        except httpx.TransportError as exc:
            _log.warning("openrouter_transport_error", model=slug, error=type(exc).__name__)
            return _Outcome(attempt("transport_error", None), retry=True)
        code = response.status_code
        if code != 200:
            _log.info("openrouter_http_error", model=slug, status=code)
            return _Outcome(attempt("http_error", code), retry=code == 429 or code >= 500)
        try:
            parsed = _ChatResponse.model_validate_json(response.content)
        except ValidationError:
            upstream = upstream_error_code(response.content)
            if upstream is None:
                return _Outcome(attempt("bad_response", code), retry=True)
            # Spec 05 § 6: OpenRouter's error object inside a 200 is that error.
            _log.info("openrouter_http_error", model=slug, status=upstream, in_body=True)
            return _Outcome(
                attempt("http_error", upstream), retry=upstream == 429 or upstream >= 500
            )
        usage = Usage(
            prompt_tokens=parsed.usage.prompt_tokens if parsed.usage else None,
            completion_tokens=parsed.usage.completion_tokens if parsed.usage else None,
        )
        if not parsed.choices:
            return _Outcome(attempt("empty", code, usage), retry=True, reply=parsed)
        choice = parsed.choices[0]
        if choice.finish_reason == "length":
            return _Outcome(attempt("length", code, usage), retry=True, reply=parsed)
        content = choice.message.content or ""
        if not content.strip():
            return _Outcome(attempt("empty", code, usage), retry=True, reply=parsed)
        extracted = extract_json_object(content)
        if extracted is None:
            return _Outcome(attempt("no_json", code, usage), retry=True, reply=parsed)
        done = attempt("ok", code, usage)
        return _Outcome(
            done,
            retry=False,
            result=ModelResult(
                text=extracted,
                served_model=slug,
                finish_reason=choice.finish_reason,
                usage=usage,
                attempts=(done,),
            ),
            reply=parsed,
        )


def _record(observed: LangfuseGeneration, outcome: _Outcome) -> None:
    """What an attempt got back, on its generation; a failed attempt is ERROR with its status."""
    reply = outcome.reply
    message = reply.choices[0].message if reply and reply.choices else None
    output: dict[str, str] | None = None
    if message is not None and (message.content or message.reasoning):
        output = {"role": "assistant", "content": message.content or ""}
        if message.reasoning:
            output["reasoning"] = message.reasoning
    usage = reply.usage if reply and reply.usage else _Usage()
    prompt = usage.prompt_tokens_details or _Details()
    completion = usage.completion_tokens_details or _Details()
    buckets = tracing.usage_details(
        prompt=usage.prompt_tokens,
        completion=usage.completion_tokens,
        cached=prompt.cached_tokens,
        reasoning=completion.reasoning_tokens,
    )
    attempt = outcome.attempt
    failed = attempt.status != "ok"
    status: str = attempt.status
    if attempt.status == "http_error" and attempt.http_status is not None:
        status = f"http_error: status={attempt.http_status}"
    observed.update(
        output=output,
        usage_details=buckets or None,
        cost_details=tracing.cost_details(usage.cost),
        metadata={"provider": reply.provider} if reply and reply.provider else None,
        level="ERROR" if failed else None,
        status_message=status if failed else None,
    )


def _with_schema(messages: list[dict[str, str]], req: ModelRequest) -> list[dict[str, str]]:
    note = (
        "\n\nAnswer with one JSON object, and nothing else, that matches this JSON Schema:\n"
        + cjson(dict(req.schema))
    )
    out = [dict(m) for m in messages]
    for m in out:
        if m["role"] == "system":
            m["content"] += note
            return out
    return [{"role": "system", "content": note.strip()}, *out]
