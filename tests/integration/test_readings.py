"""Spec 11 cases T-RD-7, T-RD-8: the `readings` table against real Postgres."""

from __future__ import annotations

import datetime as dt

import pytest
from pg import migrate
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from inkthread.models import ReadingRow
from inkthread.repositories import documents, readings

pytestmark = pytest.mark.integration

VERIFICATION = {
    "ok": True,
    "engine": "pdfium 1 (pypdfium2 2)",
    "checked": 1,
    "disagreements": 0,
    "defects": [],
}
TABLE = {
    "id": "b2",
    "node_id": None,
    "page": 1,
    "bbox": [1.0, 2.0, 3.0, 4.0],
    "header_rows": 1,
    "rows": [["Fee"], ["$1"]],
    "markdown": "| Fee |\n| --- |\n| $1 |",
}


async def _doc(s: AsyncSession) -> documents.Doc:
    return await documents.create(
        s,
        sha256="d" * 64,
        file_name="x.pdf",
        page_count=1,
        byte_size=10,
        kind="upload",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )


async def _tables(engine: AsyncEngine) -> dict[str, list[str]]:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda c: {
                t: [col["name"] for col in sa_inspect(c).get_columns(t)]
                for t in sa_inspect(c).get_table_names()
            }
        )


async def test_T_RD_7_migration_0003_creates_readings_and_is_rerunnable(
    database_url: str, engine: AsyncEngine
) -> None:
    tables = await _tables(engine)
    assert set(tables["readings"]) >= {
        "document_id",
        "schema_version",
        "inkgrid_version",
        "verification",
        "tables",
        "findings",
        "created_at",
    }
    assert ReadingRow.__table__.c.created_at.type.timezone  # type: ignore[attr-defined]
    migrate(database_url)  # the entrypoint runs it on every boot: a second run is a no-op
    migrate(database_url, "0002", down=True)
    assert "readings" not in await _tables(engine)
    migrate(database_url)
    assert "readings" in await _tables(engine)


async def test_T_RD_8_a_reading_is_replaced_and_goes_with_its_document(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as s:
        doc = await _doc(s)
        await readings.save(
            s,
            doc.id,
            inkgrid_version="0.2.0",
            verification=VERIFICATION,
            tables=[TABLE],
            findings=[],
        )
        await s.commit()
    async with sessions() as s:
        await readings.save(
            s,
            doc.id,
            inkgrid_version="0.2.1",
            verification=VERIFICATION,
            tables=[],
            findings=[{"code": "hidden_text", "severity": "warning", "page": None}],
        )
        await s.commit()
    async with sessions() as s:
        row = await readings.get(s, doc.id)
        assert row is not None
        assert row.inkgrid_version == "0.2.1"
        assert row.schema_version == "inkthread.reading/1"
        assert row.tables == []
        assert row.findings == [{"code": "hidden_text", "severity": "warning", "page": None}]
        await documents.delete(s, doc.id)
        await s.commit()
    async with sessions() as s:
        assert await readings.get(s, doc.id) is None
