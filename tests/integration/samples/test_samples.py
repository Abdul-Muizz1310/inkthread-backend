"""Task 19: the sample manifest is honest, and recorded answers round-trip."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.repositories import llm
from inkthread.services.samples import export_answers, import_answers, load_manifest

ROOT = Path(__file__).resolve().parents[3] / "samples"


def test_manifest_hashes_match_the_committed_pdfs() -> None:
    specs = load_manifest(ROOT)
    assert len(specs) >= 2
    for s in specs:
        assert hashlib.sha256(s.file.read_bytes()).hexdigest() == s.sha256, s.file


@pytest.mark.integration
async def test_answers_round_trip(
    sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    async with sessions() as s:
        await llm.put_answer(
            s, "a" * 64, task="A-classify", served_model="m", response={"labels": []}
        )
        await s.commit()
    assert await export_answers(sessions, tmp_path) == 1
    async with sessions() as s:
        await s.execute(llm.LlmResponse.__table__.delete())  # type: ignore[attr-defined]
        await s.commit()
    assert await import_answers(sessions, tmp_path) == 1
    async with sessions() as s:
        got = await llm.get_answer(s, "a" * 64)
    assert got is not None
    assert got.response == {"labels": []}


async def test_samples_are_exempt_from_the_page_cap() -> None:
    import pdfs

    from inkthread.core.errors import TooManyPages
    from inkthread.services.ingest import check_pdf

    data = pdfs.two_pages()
    assert await check_pdf(data, None) == 2
    with pytest.raises(TooManyPages):
        await check_pdf(data, 1)
