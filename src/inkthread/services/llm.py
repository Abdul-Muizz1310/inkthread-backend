"""The agent stages' ports backed by Postgres, and one job's `AgentDeps` (spec 05 § 2, § 6)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.agents.deps import AgentDeps
from inkthread.core.config import LlmMode
from inkthread.llm.budget import Budget
from inkthread.llm.ports import AnswerRecord, BudgetPort, CallLog, LlmCall, ModelPort
from inkthread.repositories import llm as llm_repo

#: Builds the model port for one job's budget (OpenRouter in production, a fake in tests).
ModelFactory = Callable[[BudgetPort], ModelPort]
#: Builds one job's agent dependencies.
AgentFactory = Callable[[uuid.UUID], AgentDeps]


class DbAnswerStore:
    """`AnswerStore` over `llm_responses`."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> AnswerRecord | None:
        async with self._sessions() as s:
            row = await llm_repo.get_answer(s, key)
        if row is None:
            return None
        return AnswerRecord(
            key=row.request_key,
            task=row.task,
            served_model=row.served_model,
            response=row.response,
            created_at=row.created_at,
        )

    async def put(self, key: str, record: AnswerRecord) -> None:
        if not isinstance(record.response, dict):
            msg = "a recorded answer must be a JSON object"
            raise TypeError(msg)
        async with self._sessions() as s, s.begin():
            await llm_repo.put_answer(
                s,
                key,
                task=record.task,
                served_model=record.served_model,
                response=record.response,
            )


class DbCallLog:
    """`CallLog` over `llm_calls`, tagged with one job."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> None:
        self._sessions = sessions
        self._job_id = job_id

    async def record(self, call: LlmCall) -> None:
        async with self._sessions() as s, s.begin():
            await llm_repo.record_call(
                s,
                job_id=self._job_id,
                task=call.task,
                model=call.model,
                request_key=call.request_key,
                cached=call.cached,
                status=call.status,
                http_status=call.http_status,
                latency_ms=call.latency_ms,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
            )


@dataclass
class CountingCallLog:
    """Forwards to a log and counts a run's traffic for the job row (spec 08 § 4)."""

    inner: CallLog
    requests: int = 0
    cached: int = 0
    failed: int = 0

    async def record(self, call: LlmCall) -> None:
        await self.inner.record(call)
        if call.cached:
            self.cached += 1
            return
        self.requests += 1
        if call.status != "ok":
            self.failed += 1


def utc_midnight(now: dt.datetime) -> dt.datetime:
    """00:00 UTC of `now`'s UTC day: the daily cap's reset."""
    return now.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class AgentSettings:
    """What `agent_factory` reads from the configuration."""

    mode: LlmMode
    primary: str
    fast: str
    fallback: str
    per_document: int
    daily_cap: int
    reserve: int
    max_tokens: int


def agent_factory(
    sessions: async_sessionmaker[AsyncSession],
    settings: AgentSettings,
    *,
    model: ModelFactory,
    account_remaining: Callable[[], Awaitable[int | None]],
) -> AgentFactory:
    """One `AgentDeps` per job: producer `[PRIMARY, FALLBACK]`, verifier `[FAST, FALLBACK]`."""
    store = DbAnswerStore(sessions)

    async def daily_count() -> int:
        async with sessions() as s:
            return await llm_repo.count_uncached_since(s, utc_midnight(dt.datetime.now(dt.UTC)))

    def build(job_id: uuid.UUID) -> AgentDeps:
        budget = Budget(
            per_document=settings.per_document,
            daily_cap=settings.daily_cap,
            reserve=settings.reserve,
            daily_count=daily_count,
            account_remaining=account_remaining,
        )
        return AgentDeps(
            model=model(budget),
            store=store,
            log=DbCallLog(sessions, job_id),
            mode=settings.mode,
            producer_cascade=(settings.primary, settings.fallback),
            verifier_cascade=(settings.fast, settings.fallback),
            max_tokens=settings.max_tokens,
        )

    return build
