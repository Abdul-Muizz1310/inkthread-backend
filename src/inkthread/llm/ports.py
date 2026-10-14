"""The LLM layer's ports and the values that cross them (spec 05 § 1).

Generic over tasks: nothing here knows about the graph. The agents build requests; adapters
(OpenRouter, Postgres, in-memory fakes) implement the protocols.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

AttemptStatus = Literal[
    "ok", "http_error", "timeout", "transport_error", "bad_response", "length", "empty", "no_json"
]


@dataclass(frozen=True)
class Message:
    """One chat message."""

    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True)
class ModelRequest:
    """What to ask, of which models, in which order."""

    task: str
    messages: tuple[Message, ...]
    schema: Mapping[str, object]
    temperature: float
    max_tokens: int
    cascade: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.cascade:
            msg = "a model request needs at least one model in its cascade"
            raise ValueError(msg)
        if not self.messages:
            msg = "a model request needs at least one message"
            raise ValueError(msg)


@dataclass(frozen=True)
class Usage:
    """Token counts the provider reported, when it did."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True)
class Attempt:
    """One HTTP attempt against one model."""

    model: str
    status: AttemptStatus
    http_status: int | None
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class ModelResult:
    """A successful completion: `text` is the JSON object extracted from the reply."""

    text: str
    served_model: str
    finish_reason: str | None
    usage: Usage
    attempts: tuple[Attempt, ...]


@dataclass(frozen=True)
class AnswerRecord:
    """A validated answer, stored under its request key."""

    key: str
    task: str
    served_model: str
    response: object
    created_at: datetime


@dataclass(frozen=True)
class LlmCall:
    """One trace row: an attempt or a recorded hit (`cached`)."""

    task: str
    model: str
    request_key: str
    cached: bool
    status: str
    http_status: int | None
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


class ModelError(Exception):
    """Base for model failures; carries every attempt made, so the caller can log them."""

    def __init__(self, attempts: Sequence[Attempt], message: str = "") -> None:
        super().__init__(message or type(self).__name__)
        self.attempts: tuple[Attempt, ...] = tuple(attempts)


class ModelUnavailable(ModelError):  # noqa: N818 - spec 05 names
    """Every model in the cascade failed, or the deadline passed."""


class ModelAuthFailed(ModelError):  # noqa: N818 - spec 05 names
    """The provider refused the key (401): the whole cascade stops."""


class BudgetExhausted(ModelError):  # noqa: N818 - spec 05 names
    """The budget refused the next attempt."""


class ModelPort(Protocol):
    """Completes a request through a cascade of models."""

    async def complete(self, req: ModelRequest) -> ModelResult:
        """Return the first good answer, or raise a `ModelError`."""
        ...


class AnswerStore(Protocol):
    """Recorded answers by request key."""

    async def get(self, key: str) -> AnswerRecord | None:
        """The record for `key`, if any."""
        ...

    async def put(self, key: str, record: AnswerRecord) -> None:
        """Store a validated answer."""
        ...


class BudgetPort(Protocol):
    """Whether one more HTTP attempt is allowed."""

    async def acquire(self) -> bool:
        """Take one request from the budget; False when none is left."""
        ...

    def spent(self) -> int:
        """Requests taken so far by this budget."""
        ...


class CallLog(Protocol):
    """The `llm_calls` trace."""

    async def record(self, call: LlmCall) -> None:
        """Append one row."""
        ...
