"""Jobs: enqueue, claim (SKIP LOCKED), finish, reap."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.models import Job


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def create(s: AsyncSession, document_id: uuid.UUID, *, request_id: str | None = None) -> Job:
    """Insert a queued job, remembering the request that queued it (spec 13 § 2)."""
    job = Job(
        document_id=document_id,
        status="queued",
        attempt=1,
        stages=[],
        llm={},
        request_id=request_id,
    )
    s.add(job)
    await s.flush()
    return job


async def get(s: AsyncSession, job_id: uuid.UUID) -> Job | None:
    """By id."""
    return await s.get(Job, job_id)


async def latest_for(s: AsyncSession, document_id: uuid.UUID) -> Job | None:
    """A document's newest job."""
    rows = await s.execute(
        select(Job).where(Job.document_id == document_id).order_by(Job.created_at.desc()).limit(1)
    )
    return rows.scalar_one_or_none()


async def active_for(s: AsyncSession, document_id: uuid.UUID) -> Job | None:
    """A document's queued or running job, if any."""
    rows = await s.execute(
        select(Job)
        .where(Job.document_id == document_id, Job.status.in_(("queued", "running")))
        .limit(1)
    )
    return rows.scalar_one_or_none()


async def count_queued(s: AsyncSession) -> int:
    """How many jobs wait."""
    return int(
        (
            await s.execute(select(func.count()).select_from(Job).where(Job.status == "queued"))
        ).scalar_one()
    )


async def claim_next(s: AsyncSession) -> Job | None:
    """Claim the oldest queued job; concurrent claimers never get the same one."""
    oldest = (
        select(Job.id)
        .where(Job.status == "queued")
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    rows = await s.execute(select(Job).where(Job.id == oldest).with_for_update())
    job = rows.scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = _now()
    job.stage = None
    await s.flush()
    return job


async def set_stage(s: AsyncSession, job_id: uuid.UUID, stage: str) -> None:
    """Record the running stage."""
    job = await s.get(Job, job_id)
    if job is not None:
        job.stage = stage
        await s.flush()


async def finish(
    s: AsyncSession,
    job_id: uuid.UUID,
    *,
    status: str,
    stages: list[dict[str, Any]],
    llm: dict[str, Any],
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Close a job with its outcome and run facts."""
    job = await s.get(Job, job_id)
    if job is None:
        return
    job.status = status
    job.finished_at = _now()
    job.stages = stages
    job.llm = llm
    job.error_code = error_code
    job.error_message = error_message
    await s.flush()


async def reap(s: AsyncSession, *, max_attempts: int) -> tuple[int, int]:
    """Requeue jobs a crash left running, or fail them once out of attempts."""
    rows = await s.execute(select(Job).where(Job.status == "running").with_for_update())
    requeued = failed = 0
    for job in rows.scalars():
        if job.attempt < max_attempts:
            job.status = "queued"
            job.attempt += 1
            job.started_at = None
            requeued += 1
        else:
            job.status = "failed"
            job.finished_at = _now()
            job.error_code = "interrupted"
            job.error_message = "the service restarted while this job ran"
            failed += 1
    await s.flush()
    return requeued, failed
