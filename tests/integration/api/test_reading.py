"""Spec 11 cases: the reading route (T-RD-9…11) and samples that replay (T-RD-12, T-RD-13)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import inkgrid
import pdfs
import pytest
from apiharness import ADMIN, Api, ApiFactory
from fake_llm import TaskModel
from inproc import read_inprocess

from inkthread.core.config import Settings
from inkthread.reader.process import ReadFailure, ReadOutcome, ReadSuccess

pytestmark = pytest.mark.integration


async def _sample(a: Api, data: bytes, name: str = "sample.pdf") -> dict[str, Any]:
    """Ingest `data` as a sample and wait for its job."""
    out = await a.app.state.services.ingest.ingest(data, name, kind="sample")
    assert out.job is not None
    return await a.wait_job(str(out.job.id))


async def test_T_RD_9_a_processed_upload_serves_its_reading(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:
    data = pdfs.ruled_table()
    async with api(run_jobs=True, settings=make_settings(llm_mode="replay")) as a:
        doc = await a.ready(data, "fees.pdf")
        r = await a.client.get(f"/documents/{doc['id']}/reading")
        assert r.status_code == 200, r.text
        assert r.headers["cache-control"] == "public, max-age=300"
        body = r.json()
        graph = (await a.client.get(f"/documents/{doc['id']}/graph")).json()
    assert set(body) == {
        "schema",
        "document_id",
        "doc_sha256",
        "inkgrid_version",
        "verification",
        "tables",
        "findings",
    }
    assert body["schema"] == "inkthread.reading/1"
    assert body["document_id"] == doc["id"]
    assert body["doc_sha256"] == doc["sha256"]
    assert body["inkgrid_version"] == inkgrid.__version__
    v = body["verification"]
    assert set(v) == {"ok", "engine", "checked", "disagreements", "defects"}
    assert v["ok"] is True
    assert v["checked"] == 1
    assert v["disagreements"] == len(v["defects"]) == 0
    (table,) = body["tables"]
    assert set(table) == {"id", "node_id", "page", "bbox", "header_rows", "rows", "markdown"}
    assert table["page"] == 1
    assert len(table["bbox"]) == 4
    assert table["header_rows"] >= 1
    assert table["markdown"].startswith("|")
    table_nodes = {n["id"] for n in graph["nodes"] if n["kind"] == "table"}
    assert table["node_id"] in table_nodes
    assert isinstance(body["findings"], list)


async def test_T_RD_10_unknown_malformed_and_not_ready(api: ApiFactory) -> None:
    async with api() as a:
        r = await a.client.get(f"/documents/{uuid.uuid4()}/reading")
        assert r.status_code == 404
        assert r.json()["error"] == "not_found"
        r = await a.client.get("/documents/not-a-uuid/reading")
        assert r.status_code == 422
        up = (await a.upload(pdfs.sectioned())).json()
        r = await a.client.get(f"/documents/{up['document']['id']}/reading")
        assert r.status_code == 409
        assert r.json()["error"] == "graph_not_ready"


async def test_T_RD_11_no_reading_for_a_failed_job(api: ApiFactory) -> None:
    async def failing(_pdf: bytes) -> ReadOutcome:
        return ReadFailure("reader_failed", "boom")

    async with api(run_jobs=True, reader=failing) as a:
        up = (await a.upload(pdfs.sectioned())).json()
        job = await a.wait_job(up["job"]["id"])
        assert job["status"] == "failed"
        r = await a.client.get(f"/documents/{up['document']['id']}/reading")
        assert r.status_code == 409


async def test_T_RD_11_a_reprocess_replaces_the_reading(api: ApiFactory) -> None:
    reads = 0

    async def counting(pdf: bytes) -> ReadOutcome:
        nonlocal reads
        reads += 1
        outcome = await read_inprocess(pdf)
        assert isinstance(outcome, ReadSuccess)
        version = f"0.2.{90 + reads}"
        digest = outcome.digest.model_copy(update={"inkgrid_version": version})
        return ReadSuccess(reading=outcome.reading, pngs=outcome.pngs, digest=digest)

    async with api(run_jobs=True, reader=counting) as a:
        job = await _sample(a, pdfs.ruled_table())
        doc_id = job["document_id"]
        first = (await a.client.get(f"/documents/{doc_id}/reading")).json()
        assert first["inkgrid_version"] == "0.2.91"
        r = await a.client.post(f"/documents/{doc_id}/reprocess", headers={"X-Admin-Token": ADMIN})
        assert r.status_code == 202
        assert (await a.wait_job(r.json()["job"]["id"]))["status"] == "succeeded"
        second = (await a.client.get(f"/documents/{doc_id}/reading")).json()
    assert second["inkgrid_version"] == "0.2.92"
    assert second["tables"] == first["tables"]


def _live(make_settings: Callable[..., Settings], **extra: object) -> Settings:
    return make_settings(llm_mode="live", openrouter_api_key="sk-test", **extra)


async def test_T_RD_12_a_sample_never_calls_a_model_but_an_upload_does(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:
    model = TaskModel()
    data = pdfs.sectioned()
    async with api(run_jobs=True, model=model, settings=_live(make_settings)) as a:
        job = await _sample(a, data)
        assert job["status"] == "succeeded"
        assert model.requests == []
        assert job["llm"]["requests"] == 0
        reasons = {s["name"]: s["reason"] for s in job["stages"]}
        assert reasons["classify_agent"] in {"replay_miss", "no_input"}
        # The same text as an upload (other bytes, so not deduplicated) does ask the model.
        await a.ready(data + b"\n% an upload\n")
        assert model.requests, "an upload keeps LLM_MODE=live"


@pytest.mark.parametrize(
    ("llm_mode", "sample_mode", "calls"),
    [("live", "live", True), ("off", "live", False), ("live", "off", False)],
)
async def test_T_RD_13_the_sample_mode_is_the_stricter_of_the_two(
    api: ApiFactory,
    make_settings: Callable[..., Settings],
    llm_mode: str,
    sample_mode: str,
    calls: bool,
) -> None:
    model = TaskModel()
    settings = make_settings(
        llm_mode=llm_mode, openrouter_api_key="sk-test", sample_llm_mode=sample_mode
    )
    async with api(run_jobs=True, model=model, settings=settings) as a:
        job = await _sample(a, pdfs.sectioned())
    assert job["status"] == "succeeded"
    assert bool(model.requests) is calls
