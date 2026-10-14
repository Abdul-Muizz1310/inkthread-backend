"""Sample documents (spec 08 § 5): seed them, and move their recorded model answers in and out."""

from __future__ import annotations

import asyncio
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.models import LlmResponse
from inkthread.repositories import llm as llm_repo
from inkthread.services.documents import DocumentService
from inkthread.services.ingest import IngestService

ANSWERS = "answers.json"


@dataclass(frozen=True)
class SampleSpec:
    """One manifest entry."""

    file: Path
    title: str
    source: str
    sha256: str


def load_manifest(root: Path) -> list[SampleSpec]:
    """Read `samples/manifest.toml`."""
    data = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
    return [
        SampleSpec(root / s["file"], s["title"], s["source"], s["sha256"])
        for s in data.get("sample", [])
    ]


async def import_answers(sessions: async_sessionmaker[AsyncSession], root: Path) -> int:
    """Load recorded answers so samples replay with zero model calls."""
    path = root / "answers" / ANSWERS
    if not path.is_file():
        return 0
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    async with sessions() as s:
        for r in rows:
            await llm_repo.put_answer(
                s,
                r["request_key"],
                task=r["task"],
                served_model=r["served_model"],
                response=r["response"],
            )
        await s.commit()
    return len(rows)


async def export_answers(sessions: async_sessionmaker[AsyncSession], root: Path) -> int:
    """Write every recorded answer, sorted by key, for committing beside the samples."""
    async with sessions() as s:
        rows = (await s.execute(select(LlmResponse).order_by(LlmResponse.request_key))).scalars()
        out = [
            {
                "request_key": r.request_key,
                "task": r.task,
                "served_model": r.served_model,
                "response": r.response,
            }
            for r in rows
        ]
    (root / "answers").mkdir(parents=True, exist_ok=True)
    (root / "answers" / ANSWERS).write_text(
        json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return len(out)


async def seed(
    ingest: IngestService,
    documents: DocumentService,
    specs: list[SampleSpec],
    *,
    timeout_s: float = 1800.0,
    poll_s: float = 2.0,
) -> dict[str, str]:
    """Ingest each sample and wait until every one is ready or failed. Returns title → status."""
    ids = {}
    for spec in specs:
        data = spec.file.read_bytes()
        out = await ingest.ingest(data, spec.file.name, kind="sample")
        ids[spec.title] = out.document.id
    done: dict[str, str] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while len(done) < len(ids) and loop.time() < deadline:
        for title, doc_id in ids.items():
            if title in done:
                continue
            status = (await documents.get(doc_id)).status
            if status in {"ready", "failed"}:
                done[title] = status
        await asyncio.sleep(poll_s)
    return {t: done.get(t, "timeout") for t in ids}
