"""Rows to DTOs: the one place that knows both the tables and the API shapes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter

from inkthread.models import Document, Job
from inkthread.schemas.documents import DocumentOut, StatsOut
from inkthread.schemas.jobs import JobError, JobOut, LlmCounts, StageOut

_STAGES: TypeAdapter[list[StageOut]] = TypeAdapter(list[StageOut])


def job_out(job: Job) -> JobOut:
    """A job row as `JobOut`."""
    error = (
        JobError(code=job.error_code, message=job.error_message or job.error_code)
        if job.error_code
        else None
    )
    return JobOut.model_validate(
        {
            "id": job.id,
            "document_id": job.document_id,
            "status": job.status,
            "stage": job.stage,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error": error,
            "llm": LlmCounts.model_validate(job.llm or {}),
            "stages": _STAGES.validate_python(job.stages or []),
        }
    )


def stats_out(stats: Mapping[str, Any] | None) -> StatsOut | None:
    """`{nodes, edges, tiers}` from a stored graph's `stats` (spec 01's `GraphStats`)."""
    if not stats:
        return None
    return StatsOut(
        nodes=sum(int(v) for v in stats.get("nodes_by_kind", {}).values()),
        edges=sum(int(v) for v in stats.get("edges_by_type", {}).values()),
        tiers={str(k): int(v) for k, v in stats.get("tiers", {}).items()},
    )


def document_out(
    doc: Document, latest: Job | None, stats: Mapping[str, Any] | None = None
) -> DocumentOut:
    """A document row, its newest job and its graph's stats as `DocumentOut`."""
    return DocumentOut.model_validate(
        {
            "id": doc.id,
            "sha256": doc.sha256,
            "file_name": doc.file_name,
            "title": doc.title,
            "page_count": doc.page_count,
            "kind": doc.kind,
            "status": doc.status,
            "created_at": doc.created_at,
            "expires_at": doc.expires_at,
            "stats": stats_out(stats),
            "latest_job": job_out(latest) if latest is not None else None,
        }
    )
