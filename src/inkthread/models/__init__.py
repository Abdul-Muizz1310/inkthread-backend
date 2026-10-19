"""ORM tables (spec 08 § 1). Only repositories import these."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    """Declarative base."""


TS = DateTime(timezone=True)


class Document(Base):
    """An uploaded or sample PDF."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("kind in ('sample', 'upload')", name="documents_kind"),
        CheckConstraint(
            "status in ('queued', 'processing', 'ready', 'failed')", name="documents_status"
        ),
        CheckConstraint("page_count > 0", name="documents_pages"),
        CheckConstraint("byte_size > 0", name="documents_bytes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    file_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer)
    byte_size: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        TS, default=_now, onupdate=_now, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(TS)


class Job(Base):
    """One pipeline run over a document."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed')", name="jobs_status"
        ),
        Index("jobs_queue", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str | None] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())
    started_at: Mapped[dt.datetime | None] = mapped_column(TS)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    llm: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class JobEvent(Base):
    """A persisted event: the build log and the SSE replay source."""

    __tablename__ = "job_events"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())


class GraphRow(Base):
    """A document's finished graph and its op log."""

    __tablename__ = "graphs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    schema_version: Mapped[str] = mapped_column(String(32))
    graph_hash: Mapped[str] = mapped_column(String(64))
    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ops: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())


class ReadingRow(Base):
    """What spec 11 keeps of a document's inkgrid reading: tables and the verification summary."""

    __tablename__ = "readings"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    schema_version: Mapped[str] = mapped_column(String(32))
    inkgrid_version: Mapped[str] = mapped_column(String(32))
    verification: Mapped[dict[str, Any]] = mapped_column(JSONB)
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())


class LlmCall(Base):
    """One model attempt or cache hit (convention-llm-usage: every call is traced)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    task: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(Text)
    request_key: Mapped[str] = mapped_column(String(64))
    cached: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(32))
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        TS, default=_now, server_default=func.now(), index=True
    )


class LlmResponse(Base):
    """A recorded, schema-valid model answer, keyed by its request."""

    __tablename__ = "llm_responses"

    request_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(32))
    served_model: Mapped[str] = mapped_column(Text)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())


class BlobRow(Base):
    """A blob kept in Postgres when no object store is configured."""

    __tablename__ = "blobs"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now, server_default=func.now())
