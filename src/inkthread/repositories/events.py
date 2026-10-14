"""Job events: the build log and the SSE replay source."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.models import JobEvent


async def append(s: AsyncSession, job_id: uuid.UUID, type_: str, payload: dict[str, Any]) -> int:
    """Append an event; returns its sequence number (1, 2, …). One writer per job."""
    last = (
        await s.execute(
            select(func.coalesce(func.max(JobEvent.seq), 0)).where(JobEvent.job_id == job_id)
        )
    ).scalar_one()
    seq = int(last) + 1
    s.add(JobEvent(job_id=job_id, seq=seq, type=type_, payload=payload))
    await s.flush()
    return seq


async def after(s: AsyncSession, job_id: uuid.UUID, seq: int) -> list[JobEvent]:
    """Events with `seq > seq`, in order."""
    rows = await s.execute(
        select(JobEvent).where(JobEvent.job_id == job_id, JobEvent.seq > seq).order_by(JobEvent.seq)
    )
    return list(rows.scalars())
