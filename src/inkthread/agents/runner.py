"""One model task, end to end (spec 05 § 2): key → recorded answer → budget → model → schema."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ValidationError

from inkthread.agents.deps import AgentDeps, SkipReason
from inkthread.agents.prompts import DATA_LINE, Prompt
from inkthread.canon import cjson
from inkthread.core.config import LlmMode
from inkthread.llm.keys import request_key
from inkthread.llm.ports import (
    AnswerRecord,
    Attempt,
    BudgetExhausted,
    LlmCall,
    Message,
    ModelError,
    ModelRequest,
)

TaskStatus = Literal["answered", "cached", "abstained"]


@dataclass(frozen=True)
class TaskOutcome[A: BaseModel]:
    """The result of one task call. `answer` and `served_model` are set unless it abstained."""

    status: TaskStatus
    request_key: str
    answer: A | None = None
    served_model: str | None = None
    reason: SkipReason | None = None
    attempts: tuple[Attempt, ...] = field(default=())

    @property
    def calls(self) -> int:
        """HTTP attempts this outcome cost."""
        return len(self.attempts)


async def run_task[A: BaseModel](
    *,
    prompt: Prompt,
    answer_model: type[A],
    schema: Mapping[str, object],
    payload: object,
    cascade: Sequence[str],
    deps: AgentDeps,
) -> TaskOutcome[A]:
    """Answer one task input, from the record when one exists, else from the model when allowed.

    Every attempt and every recorded hit is written to the call log. Only answers that parse and
    validate are stored; grounding is the caller's job and is re-run on every replay.
    """
    temperature = prompt.temperature if deps.temperature is None else deps.temperature
    key = request_key(
        prompt.task, prompt.version, schema, prompt.raw, cascade, temperature, payload
    )
    if deps.mode is LlmMode.OFF:
        return TaskOutcome(status="abstained", request_key=key, reason="disabled")

    record = await deps.store.get(key)
    if record is not None:
        try:
            answer = answer_model.model_validate(record.response)
        except ValidationError:
            record = None
        else:
            await deps.log.record(
                LlmCall(
                    task=prompt.task,
                    model=record.served_model,
                    request_key=key,
                    cached=True,
                    status="hit",
                    http_status=None,
                    latency_ms=0,
                    prompt_tokens=None,
                    completion_tokens=None,
                )
            )
            return TaskOutcome(
                status="cached", request_key=key, answer=answer, served_model=record.served_model
            )
    if deps.mode is LlmMode.REPLAY:
        return TaskOutcome(status="abstained", request_key=key, reason="replay_miss")

    request = ModelRequest(
        task=prompt.task,
        messages=(
            Message(role="system", content=prompt.body),
            Message(role="user", content=f"{DATA_LINE}\n{cjson(payload)}"),
        ),
        schema=schema,
        temperature=temperature,
        max_tokens=min(prompt.max_tokens, deps.max_tokens),
        cascade=tuple(cascade),
    )
    try:
        result = await deps.model.complete(request)
    except ModelError as exc:
        await _log_attempts(deps, prompt.task, key, exc.attempts)
        reason: SkipReason = "budget" if isinstance(exc, BudgetExhausted) else "model_unavailable"
        return TaskOutcome(
            status="abstained", request_key=key, reason=reason, attempts=exc.attempts
        )
    await _log_attempts(deps, prompt.task, key, result.attempts)
    try:
        response: object = json.loads(result.text)
        answer = answer_model.model_validate(response)
    except (json.JSONDecodeError, ValidationError):
        return TaskOutcome(
            status="abstained",
            request_key=key,
            reason="invalid_answer",
            served_model=result.served_model,
            attempts=result.attempts,
        )
    await deps.store.put(
        key,
        AnswerRecord(
            key=key,
            task=prompt.task,
            served_model=result.served_model,
            response=response,
            created_at=datetime.now(UTC),
        ),
    )
    return TaskOutcome(
        status="answered",
        request_key=key,
        answer=answer,
        served_model=result.served_model,
        attempts=result.attempts,
    )


async def _log_attempts(deps: AgentDeps, task: str, key: str, attempts: Sequence[Attempt]) -> None:
    for a in attempts:
        await deps.log.record(
            LlmCall(
                task=task,
                model=a.model,
                request_key=key,
                cached=False,
                status=a.status,
                http_status=a.http_status,
                latency_ms=a.latency_ms,
                prompt_tokens=a.prompt_tokens,
                completion_tokens=a.completion_tokens,
            )
        )
