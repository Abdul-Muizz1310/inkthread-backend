"""Spec 08 § 6: T-PJ-1…7 and T-PJ-14 against real Postgres."""

from __future__ import annotations

import asyncio
import datetime as dt
from pathlib import Path

import pytest
from pg import migrate
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from inkthread.models import Base
from inkthread.repositories import documents, events, graphs, jobs, llm
from inkthread.storage.blobs import LocalBlobStore

pytestmark = pytest.mark.integration
UTC = dt.UTC


async def new_doc(s: AsyncSession, sha: str = "a" * 64, kind: str = "upload") -> documents.Doc:
    return await documents.create(
        s,
        sha256=sha,
        file_name="x.pdf",
        page_count=2,
        byte_size=10,
        kind=kind,
        expires_at=None if kind == "sample" else dt.datetime.now(UTC) + dt.timedelta(days=7),
    )


async def test_migrations_round_trip_and_timestamps_are_tz_aware(
    database_url: str, engine: AsyncEngine
) -> None:  # T-PJ-1
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda c: {
                (t, col["name"]): col["type"]
                for t in sa_inspect(c).get_table_names()
                for col in sa_inspect(c).get_columns(t)
            }
        )
    stamps = {k: v for k, v in cols.items() if "TIMESTAMP" in str(v).upper()}
    assert stamps
    assert all(getattr(v, "timezone", False) for v in stamps.values())
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if "DateTime" in type(column.type).__name__:
                assert column.type.timezone, f"{table.name}.{column.name}"  # type: ignore[attr-defined]
    migrate(database_url, "base", down=True)
    migrate(database_url)


async def test_sha_unique_and_cascades(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:  # T-PJ-2
        doc = await new_doc(s)
        job = await jobs.create(s, doc.id)
        await events.append(s, job.id, "stage", {"stage": "read"})
        await graphs.save(s, doc.id, graph={"schema": "x"}, graph_hash="h" * 64, ops=[])
        await llm.record_call(
            s,
            job_id=job.id,
            task="A-classify",
            model="m",
            request_key="k" * 64,
            cached=False,
            status="ok",
            http_status=200,
            latency_ms=5,
        )
        await s.commit()
    async with sessions() as s:
        with pytest.raises(IntegrityError):
            await new_doc(s)
    async with sessions() as s:
        await documents.delete(s, doc.id)
        await s.commit()
    async with sessions() as s:
        assert await jobs.get(s, job.id) is None
        assert await events.after(s, job.id, 0) == []
        assert await graphs.get(s, doc.id) is None
        calls = await llm.calls_for_task(s, "A-classify")
        assert [c.job_id for c in calls] == [None]


async def test_concurrent_claims_never_share_a_job(
    sessions: async_sessionmaker[AsyncSession],
) -> None:  # T-PJ-3
    async with sessions() as s:
        a = await new_doc(s, "a" * 64)
        b = await new_doc(s, "b" * 64)
        await jobs.create(s, a.id)
        await jobs.create(s, b.id)
        await s.commit()

    async def claim() -> str | None:
        async with sessions() as s:
            job = await jobs.claim_next(s)
            await asyncio.sleep(0.05)
            await s.commit()
            return str(job.id) if job else None

    got = await asyncio.gather(claim(), claim(), claim())
    claimed = [g for g in got if g]
    assert len(claimed) == 2
    assert len(set(claimed)) == 2


async def test_events_are_ordered_per_job(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:  # T-PJ-4
        doc = await new_doc(s)
        job = await jobs.create(s, doc.id)
        seqs = [await events.append(s, job.id, "stage", {"n": i}) for i in range(5)]
        await s.commit()
        assert seqs == [1, 2, 3, 4, 5]
        assert [e.seq for e in await events.after(s, job.id, 2)] == [3, 4, 5]
        assert [e.payload["n"] for e in await events.after(s, job.id, 0)] == [0, 1, 2, 3, 4]


async def test_daily_count_is_uncached_today_utc(
    sessions: async_sessionmaker[AsyncSession],
) -> None:  # T-PJ-5
    now = dt.datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
    async with sessions() as s:
        for cached, when in [
            (False, now),
            (False, now - dt.timedelta(hours=11)),
            (True, now),
            (False, now - dt.timedelta(days=1)),
        ]:
            await llm.record_call(
                s,
                job_id=None,
                task="A-classify",
                model="m",
                request_key="k" * 64,
                cached=cached,
                status="ok",
                http_status=200,
                latency_ms=1,
                created_at=when,
            )
        await s.commit()
        assert await llm.count_uncached_since(s, now.replace(hour=0)) == 2


async def test_reaper_requeues_once_then_fails(
    sessions: async_sessionmaker[AsyncSession],
) -> None:  # T-PJ-6
    async with sessions() as s:
        doc = await new_doc(s)
        job = await jobs.create(s, doc.id)
        await s.commit()
    for expected in ("queued", "failed"):
        async with sessions() as s:
            claimed = await jobs.claim_next(s)
            assert claimed is not None
            await s.commit()
        async with sessions() as s:
            await jobs.reap(s, max_attempts=2)
            await s.commit()
            row = await jobs.get(s, job.id)
            assert row is not None
            assert row.status == expected
    assert row.error_code == "interrupted"


async def test_retention_finds_expired_uploads_only(
    sessions: async_sessionmaker[AsyncSession],
) -> None:  # T-PJ-7
    now = dt.datetime.now(UTC)
    async with sessions() as s:
        old = await documents.create(
            s,
            sha256="1" * 64,
            file_name=None,
            page_count=1,
            byte_size=1,
            kind="upload",
            expires_at=now - dt.timedelta(hours=1),
        )
        await documents.create(
            s,
            sha256="2" * 64,
            file_name=None,
            page_count=1,
            byte_size=1,
            kind="upload",
            expires_at=now + dt.timedelta(hours=1),
        )
        await documents.create(
            s,
            sha256="3" * 64,
            file_name=None,
            page_count=1,
            byte_size=1,
            kind="sample",
            expires_at=None,
        )
        await s.commit()
        assert [d.id for d in await documents.expired_uploads(s, now)] == [old.id]


async def test_answers_round_trip(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as s:
        await llm.put_answer(s, "k" * 64, task="A-classify", served_model="m", response={"a": 1})
        await llm.put_answer(s, "k" * 64, task="A-classify", served_model="m", response={"a": 1})
        await s.commit()
        got = await llm.get_answer(s, "k" * 64)
        assert got is not None
        assert got.response == {"a": 1}


def test_local_blob_store_round_trip(tmp_path: Path) -> None:  # T-PJ-14
    store = LocalBlobStore(tmp_path)
    asyncio.run(store.put("pages/x/1.png", b"png", "image/png"))
    asyncio.run(store.put("pages/x/2.png", b"png2", "image/png"))
    assert asyncio.run(store.get("pages/x/1.png")) == b"png"
    assert asyncio.run(store.get("pages/x/none.png")) is None
    asyncio.run(store.delete_prefix("pages/x/"))
    assert asyncio.run(store.get("pages/x/2.png")) is None
    with pytest.raises(ValueError, match="key"):
        asyncio.run(store.put("../escape", b"", "text/plain"))
