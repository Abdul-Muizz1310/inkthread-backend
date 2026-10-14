"""Document DTOs (spec 07 § 2; mirrored by the frontend's `DocumentOut` and `UploadOut`)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from inkthread.domain.model import Bbox
from inkthread.schemas.jobs import JobOut

DocumentKind = Literal["sample", "upload"]
DocumentStatus = Literal["queued", "processing", "ready", "failed"]


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StatsOut(_Out):
    """The graph's size: node and edge counts, and how many elements sit in each tier."""

    nodes: int
    edges: int
    tiers: dict[str, int]


class DocumentOut(_Out):
    """A document with its latest job; `stats` once its graph exists."""

    id: uuid.UUID
    sha256: str
    file_name: str | None
    title: str | None
    page_count: int
    kind: DocumentKind
    status: DocumentStatus
    created_at: dt.datetime
    expires_at: dt.datetime | None
    stats: StatsOut | None
    latest_job: JobOut | None


class UploadOut(_Out):
    """What an upload or a reprocess returns."""

    document: DocumentOut
    job: JobOut | None
    deduplicated: bool = False


class SamplesOut(_Out):
    """The curated samples."""

    items: list[DocumentOut]


class GeometryWord(_Out):
    """One word on a page: its node, its span in that node's text, and its box (spec 02 § 9)."""

    node: str | None
    start: int | None
    end: int | None
    bbox: Bbox
