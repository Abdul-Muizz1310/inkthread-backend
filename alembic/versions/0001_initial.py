"""initial schema (spec 08 § 1)

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("file_name", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", TS),
        sa.CheckConstraint("kind in ('sample', 'upload')", name="documents_kind"),
        sa.CheckConstraint(
            "status in ('queued', 'processing', 'ready', 'failed')", name="documents_status"
        ),
        sa.CheckConstraint("page_count > 0", name="documents_pages"),
        sa.CheckConstraint("byte_size > 0", name="documents_bytes"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(32)),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("stages", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("llm", pg.JSONB(), nullable=False, server_default="{}"),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'succeeded', 'failed')", name="jobs_status"
        ),
    )
    op.create_index("ix_jobs_document_id", "jobs", ["document_id"])
    op.create_index("jobs_queue", "jobs", ["status", "created_at"])
    op.create_table(
        "job_events",
        sa.Column(
            "job_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "graphs",
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("graph_hash", sa.String(64), nullable=False),
        sa.Column("graph", pg.JSONB(), nullable=False),
        sa.Column("ops", pg.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id", pg.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")
        ),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])
    op.create_table(
        "llm_responses",
        sa.Column("request_key", sa.String(64), primary_key=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("served_model", sa.Text(), nullable=False),
        sa.Column("response", pg.JSONB(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("llm_responses")
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_table("graphs")
    op.drop_table("job_events")
    op.drop_index("jobs_queue", table_name="jobs")
    op.drop_index("ix_jobs_document_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("documents")
