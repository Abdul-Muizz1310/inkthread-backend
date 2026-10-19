"""Readings: what spec 11 keeps of a document's inkgrid reading."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.domain.digest import READING_SCHEMA
from inkthread.models import ReadingRow


async def save(
    s: AsyncSession,
    document_id: uuid.UUID,
    *,
    inkgrid_version: str,
    verification: dict[str, Any],
    tables: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> None:
    """Insert or replace a document's reading."""
    values = {
        "document_id": document_id,
        "schema_version": READING_SCHEMA,
        "inkgrid_version": inkgrid_version,
        "verification": verification,
        "tables": tables,
        "findings": findings,
        "created_at": dt.datetime.now(dt.UTC),
    }
    stmt = insert(ReadingRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ReadingRow.document_id],
        set_={k: stmt.excluded[k] for k in values if k != "document_id"},
    )
    await s.execute(stmt)


async def get(s: AsyncSession, document_id: uuid.UUID) -> ReadingRow | None:
    """A document's reading."""
    return await s.get(ReadingRow, document_id)
