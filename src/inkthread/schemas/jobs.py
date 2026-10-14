"""Job DTOs (spec 07 § 2; mirrored by the frontend's `JobOut`)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class JobError(_Out):
    """Why a job failed."""

    code: str
    message: str


class LlmCounts(_Out):
    """Model traffic of one run: HTTP requests, recorded hits, failed attempts, refused claims."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    requests: int = Field(default=0, ge=0)
    cached: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)


class StageOut(_Out):
    """One stage's outcome."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    status: str
    ms: int | None = None
    reason: str | None = None


class JobOut(_Out):
    """A job's status and run facts."""

    id: uuid.UUID
    document_id: uuid.UUID
    status: JobStatus
    stage: str | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    error: JobError | None
    llm: LlmCounts
    stages: list[StageOut]
