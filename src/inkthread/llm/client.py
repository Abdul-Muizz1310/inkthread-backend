"""OpenRouter chat completions with a cascade, retries and a budget (spec 05 § 6)."""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import structlog
from pydantic import BaseModel, SecretStr, ValidationError

from inkthread.canon import cjson
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
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class _ChatMessage(BaseModel):
    content: str | None = None


class _Choice(BaseModel):
    message: _ChatMessage
    finish_reason: str | None = None


class _Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class _ChatResponse(BaseModel):
    choices: list[_Choice]
    usage: _Usage | None = None


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
    attempt: Attempt
    retry: bool
    result: ModelResult | None = None


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
            body = await self._body(req, slug)
            for n in range(ATTEMPTS_PER_MODEL):
                remaining = self._deadline - (self.clock() - started)
                if remaining <= 0:
                    raise ModelUnavailable(attempts, "the cascade deadline passed")
                if not await self._budget.acquire():
                    raise BudgetExhausted(attempts, "the request budget is spent")
                outcome = await self._attempt(slug, body, min(self._timeout, remaining))
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

    async def _body(self, req: ModelRequest, slug: str) -> dict[str, object]:
        caps = await self._catalog.capabilities(slug)
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        body: dict[str, object] = {
            "model": slug,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens or self._max_tokens,
            "reasoning": {"effort": "low"},
        }
        if caps.structured_outputs:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": req.task, "strict": True, "schema": dict(req.schema)},
            }
        else:
            messages = _with_schema(messages, req)
            if caps.response_format:
                body["response_format"] = {"type": "json_object"}
        body["messages"] = messages
        return body

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
            return _Outcome(attempt("bad_response", code), retry=True)
        usage = Usage(
            prompt_tokens=parsed.usage.prompt_tokens if parsed.usage else None,
            completion_tokens=parsed.usage.completion_tokens if parsed.usage else None,
        )
        if not parsed.choices:
            return _Outcome(attempt("empty", code, usage), retry=True)
        choice = parsed.choices[0]
        if choice.finish_reason == "length":
            return _Outcome(attempt("length", code, usage), retry=True)
        content = choice.message.content or ""
        if not content.strip():
            return _Outcome(attempt("empty", code, usage), retry=True)
        extracted = extract_json_object(content)
        if extracted is None:
            return _Outcome(attempt("no_json", code, usage), retry=True)
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
