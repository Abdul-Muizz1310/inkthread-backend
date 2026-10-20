"""jobs.request_id: the upload's X-Request-Id, so a job's queries are attributed to it (spec 13)

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The entrypoint migrates on every boot; IF NOT EXISTS keeps a re-run harmless.
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS request_id varchar(128)")


def downgrade() -> None:
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS request_id")
