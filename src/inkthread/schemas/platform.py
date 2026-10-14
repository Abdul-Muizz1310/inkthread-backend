"""Health and version DTOs (spec 10 § 2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthOut(BaseModel):
    """Liveness plus the database's state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "degraded"]
    version: str
    commit_sha: str
    db: Literal["ok", "down"]


class VersionOut(BaseModel):
    """What is deployed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    commit_sha: str
    pipeline_version: str
    inkgrid_version: str
    graph_schema: str


class ErrorOut(BaseModel):
    """The error envelope (spec 07 § 1), for the OpenAPI document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    error: str
    message: str
    detail: dict[str, object] | None = None
