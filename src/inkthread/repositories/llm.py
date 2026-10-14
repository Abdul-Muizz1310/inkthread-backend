"""Model call traces and recorded answers."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.models import LlmCall, LlmResponse


async def record_call(
    s: AsyncSession,
    *,
    job_id: uuid.UUID | None,
    task: str,
    model: str | None,
    request_key: str,
    cached: bool,
    status: str,
    http_status: int | None,
    latency_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    created_at: dt.datetime | None = None,
) -> None:
    """Trace one attempt or cache hit."""
    row = LlmCall(
        job_id=job_id,
        task=task,
        model=model,
        request_key=request_key,
        cached=cached,
        status=status,
        http_status=http_status,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    if created_at is not None:
        row.created_at = created_at
    s.add(row)
    await s.flush()


async def count_uncached_since(s: AsyncSession, since: dt.datetime) -> int:
    """Attempts (not cache hits) since a moment: the daily budget's counter."""
    q = (
        select(func.count())
        .select_from(LlmCall)
        .where(LlmCall.cached.is_(False), LlmCall.created_at >= since)
    )
    return int((await s.execute(q)).scalar_one())


async def calls_for_task(s: AsyncSession, task: str) -> list[LlmCall]:
    """Traces of one task, oldest first."""
    rows = await s.execute(select(LlmCall).where(LlmCall.task == task).order_by(LlmCall.id))
    return list(rows.scalars())


async def get_answer(s: AsyncSession, request_key: str) -> LlmResponse | None:
    """A recorded answer."""
    return await s.get(LlmResponse, request_key)


async def put_answer(
    s: AsyncSession, request_key: str, *, task: str, served_model: str, response: dict[str, Any]
) -> None:
    """Record an answer; the first one recorded for a key wins."""
    stmt = insert(LlmResponse).values(
        request_key=request_key, task=task, served_model=served_model, response=response
    )
    await s.execute(stmt.on_conflict_do_nothing(index_elements=[LlmResponse.request_key]))
