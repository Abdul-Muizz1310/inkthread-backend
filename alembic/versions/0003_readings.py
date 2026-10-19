"""readings: inkgrid's tables and verification summary per document (spec 11)

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The entrypoint migrates on every boot; IF NOT EXISTS keeps a re-run harmless even if the
    # version stamp were ever lost.
    op.create_table(
        "readings",
        sa.Column(
            "document_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("inkgrid_version", sa.String(32), nullable=False),
        sa.Column("verification", pg.JSONB(), nullable=False),
        sa.Column("tables", pg.JSONB(), nullable=False),
        sa.Column("findings", pg.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("readings", if_exists=True)
