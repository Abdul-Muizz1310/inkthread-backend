"""Finished graphs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from inkthread.models import GraphRow


async def save(
    s: AsyncSession,
    document_id: uuid.UUID,
    *,
    graph: dict[str, Any],
    graph_hash: str,
    ops: list[dict[str, Any]],
) -> None:
    """Insert or replace a document's graph."""
    values = {
        "document_id": document_id,
        "schema_version": str(graph.get("schema", "")),
        "graph_hash": graph_hash,
        "graph": graph,
        "ops": ops,
    }
    stmt = insert(GraphRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[GraphRow.document_id],
        set_={k: stmt.excluded[k] for k in ("schema_version", "graph_hash", "graph", "ops")},
    )
    await s.execute(stmt)


async def get(s: AsyncSession, document_id: uuid.UUID) -> GraphRow | None:
    """A document's graph."""
    return await s.get(GraphRow, document_id)


async def stats(s: AsyncSession, document_id: uuid.UUID) -> dict[str, Any] | None:
    """A stored graph's `stats` object, without loading the graph."""
    q = select(GraphRow.graph["stats"]).where(GraphRow.document_id == document_id)
    value = (await s.execute(q)).scalar_one_or_none()
    return value if isinstance(value, dict) else None
