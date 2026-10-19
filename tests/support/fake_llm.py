"""Test doubles for the LLM ports: a scripted model, in-memory store and log, a budget."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from inkthread.llm.budget import utc_day
from inkthread.llm.ports import (
    AnswerRecord,
    Attempt,
    BudgetExhausted,
    BudgetPort,
    LlmCall,
    ModelRequest,
    ModelResult,
    ModelUnavailable,
    Usage,
)


@dataclass(frozen=True)
class Reply:
    """One scripted answer: the reply text and the model that served it."""

    text: str
    served_model: str = "fake/producer"


@dataclass
class ScriptedModel:
    """A `ModelPort` that answers from a script, one entry per `complete` call.

    An entry that is an exception is raised instead. Each call spends one budget unit when a budget
    is given, and counts as one attempt.
    """

    script: list[Reply | Exception]
    budget: BudgetPort | None = None
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(self, req: ModelRequest) -> ModelResult:
        if self.budget is not None and not await self.budget.acquire():
            raise BudgetExhausted(())
        self.requests.append(req)
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        attempt = Attempt(
            model=entry.served_model,
            status="ok",
            http_status=200,
            latency_ms=1,
            prompt_tokens=10,
            completion_tokens=5,
        )
        return ModelResult(
            text=entry.text,
            served_model=entry.served_model,
            finish_reason="stop",
            usage=Usage(prompt_tokens=10, completion_tokens=5),
            attempts=(attempt,),
        )


def unavailable(model: str = "fake/producer") -> ModelUnavailable:
    """A cascade that failed after one attempt."""
    return ModelUnavailable(
        (
            Attempt(
                model=model,
                status="http_error",
                http_status=503,
                latency_ms=1,
                prompt_tokens=None,
                completion_tokens=None,
            ),
        )
    )


@dataclass
class MemoryStore:
    """An in-memory `AnswerStore`."""

    records: dict[str, AnswerRecord] = field(default_factory=dict)

    async def get(self, key: str) -> AnswerRecord | None:
        return self.records.get(key)

    async def put(self, key: str, record: AnswerRecord) -> None:
        self.records[key] = record


@dataclass
class MemoryCallLog:
    """An in-memory `CallLog` that can count today's uncached attempts (UTC)."""

    calls: list[tuple[datetime, LlmCall]] = field(default_factory=list)
    now: datetime = field(default_factory=lambda: datetime(2026, 10, 14, 12, tzinfo=UTC))

    async def record(self, call: LlmCall) -> None:
        self.calls.append((self.now, call))

    async def count_today(self) -> int:
        today = utc_day(self.now)
        return sum(1 for at, c in self.calls if not c.cached and utc_day(at) == today)

    @property
    def entries(self) -> list[LlmCall]:
        return [c for _, c in self.calls]


@dataclass
class CountingBudget:
    """A `BudgetPort` that allows `limit` acquisitions."""

    limit: int = 1000
    used: int = 0

    async def acquire(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    def spent(self) -> int:
        return self.used


EMPTY_ANSWERS = {
    "classify": '{"labels": []}',
    "relate": '{"relations": []}',
    "verify": '{"verdicts": []}',
}


class TaskModel:
    """A model that gives each task a valid, empty answer, and counts the requests."""

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, req: ModelRequest) -> ModelResult:
        self.requests.append(req)
        reply = Reply(EMPTY_ANSWERS[req.task], served_model=req.cascade[0])
        attempt = Attempt(reply.served_model, "ok", 200, 1, 10, 5)
        return ModelResult(reply.text, reply.served_model, "stop", Usage(10, 5), (attempt,))
