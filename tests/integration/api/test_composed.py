"""Spec 08 § 6 composed cases: upload → runner → stream → graph (T-PJ-12), replay (T-PJ-13)."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable
from typing import Any

import pdfs
import pytest
from apiharness import ApiFactory, parse_sse
from fake_llm import TaskModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core.config import Settings
from inkthread.domain.explain import explain
from inkthread.domain.model import Graph
from inkthread.domain.ops import Op
from inkthread.models import LlmCall
from inkthread.reader.adapt import adapt
from inkthread.repositories import graphs

pytestmark = pytest.mark.integration


async def test_upload_to_graph_end_to_end(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:  # T-PJ-12
    async with api(run_jobs=True, settings=make_settings(llm_mode="replay")) as a:
        data = pdfs.sectioned()
        up = await a.upload(data, "rules.pdf")
        assert up.status_code == 202
        body = up.json()
        stream = parse_sse((await a.client.get(f"/jobs/{body['job']['id']}/events")).text)
        assert stream[-1]["event"] == "done"
        doc_id = body["document"]["id"]
        graph_json = (await a.client.get(f"/documents/{doc_id}/graph")).json()
        graph = Graph.model_validate(graph_json)
        assert graph.provenance.graph_hash == stream[-1]["data"]["graph_hash"]
        job: dict[str, Any] = (await a.client.get(f"/jobs/{body['job']['id']}")).json()
        assert job["status"] == "succeeded"
        assert job["stages"][0]["name"] == "read"
        assert {s["name"]: s["reason"] for s in job["stages"]}["classify_agent"] in {
            "replay_miss",
            "no_input",
        }
        assert job["finished_at"] is not None
        doc = (await a.client.get(f"/documents/{doc_id}")).json()
        assert doc["status"] == "ready"
        assert doc["title"] == pdfs.SECTIONED_TITLE
        # The explain gate passes on what the API serves.
        import inkgrid

        reading = adapt(inkgrid.read(data), inkgrid.verify(inkgrid.read(data), data))
        reading = reading.model_copy(update={"file_name": "rules.pdf"})
        ops = await _ops(a.app, uuid.UUID(doc_id))
        assert explain(graph, reading, ops) == []
        png = await a.client.get(f"/documents/{doc_id}/pages/1.png")
        assert png.status_code == 200
        assert png.content
        geometry = await a.client.get(f"/documents/{doc_id}/pages/1/geometry")
        assert geometry.status_code == 200
        node_ids = {n.id for n in graph.nodes}
        assert {w["node"] for w in geometry.json() if w["node"]} <= node_ids


async def _ops(app: Any, doc_id: uuid.UUID) -> list[Op]:
    sessions = app.state.services.sessions
    async with sessions() as s:
        row = await graphs.get(s, doc_id)
    assert row is not None
    return [Op.model_validate(o) for o in row.ops]


async def _uncached_calls(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as s:
        q = select(func.count()).select_from(LlmCall).where(LlmCall.cached.is_(False))
        return int((await s.execute(q)).scalar_one())


async def test_replay_gives_the_same_graph_with_zero_requests(
    api: ApiFactory,
    make_settings: Callable[..., Settings],
    sessions: async_sessionmaker[AsyncSession],
) -> None:  # T-PJ-13
    data = pdfs.sectioned()
    live = TaskModel()
    live_settings = make_settings(llm_mode="live", openrouter_api_key="sk-test")
    async with api(run_jobs=True, model=live, settings=live_settings) as a:
        first = await a.ready(data)
        first_graph = (await a.client.get(f"/documents/{first['id']}/graph")).json()
    assert live.requests, "the live run should have asked the model"
    calls_after_live = await _uncached_calls(sessions)
    assert calls_after_live == len(live.requests)
    replay = TaskModel()
    shutil.rmtree(a.upload_root / "pages" / first["sha256"])  # a restart lost the upload's files
    async with api(run_jobs=True, model=replay, settings=make_settings(llm_mode="replay")) as a:
        r = await a.upload(data)  # so the same bytes are processed again (T-PJ-17, T-PJ-18)
        assert r.status_code == 202
        job = await a.wait_job(r.json()["job"]["id"])
        assert job["status"] == "succeeded"
        assert job["llm"]["requests"] == 0
        assert job["llm"]["cached"] == len(live.requests)
        second_graph = (await a.client.get(f"/documents/{job['document_id']}/graph")).json()
    assert replay.requests == []
    assert await _uncached_calls(sessions) == calls_after_live
    assert second_graph["provenance"]["graph_hash"] == first_graph["provenance"]["graph_hash"]
