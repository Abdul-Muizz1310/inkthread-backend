"""Spec 07 § 5 read cases (T-API-7…12)."""

from __future__ import annotations

import uuid

import pdfs
import pytest
from apiharness import ApiFactory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.repositories import documents

pytestmark = pytest.mark.integration


async def test_unknown_and_malformed_document_ids(api: ApiFactory) -> None:  # T-API-7
    async with api() as a:
        r = await a.client.get(f"/documents/{uuid.uuid4()}")
        assert r.status_code == 404
        assert r.json()["error"] == "not_found"
        r = await a.client.get("/documents/not-a-uuid")
        assert r.status_code == 422
        assert r.json()["error"] == "validation_error"
        assert r.json()["detail"] is not None


async def test_graph_is_409_until_ready_then_cached(api: ApiFactory) -> None:  # T-API-8
    async with api() as a:
        up = (await a.upload(pdfs.sectioned())).json()
        r = await a.client.get(f"/documents/{up['document']['id']}/graph")
        assert r.status_code == 409
        assert r.json()["error"] == "graph_not_ready"
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        assert doc["status"] == "ready"
        assert doc["stats"]["nodes"] > 0
        assert set(doc["stats"]) == {"nodes", "edges", "tiers"}
        assert doc["latest_job"]["status"] == "succeeded"
        r = await a.client.get(f"/documents/{doc['id']}/graph")
        assert r.status_code == 200
        graph = r.json()
        assert graph["schema"] == "inkthread.graph/1"
        etag = r.headers["etag"]
        assert etag == f'"{graph["provenance"]["graph_hash"]}"'
        assert r.headers["cache-control"] == "public, max-age=300"
        again = await a.client.get(f"/documents/{doc['id']}/graph", headers={"if-none-match": etag})
        assert again.status_code == 304
        assert again.content == b""


async def test_exports(api: ApiFactory) -> None:  # T-API-9
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        for fmt, media in (
            ("jsonld", "application/ld+json"),
            ("graphml", "application/graphml+xml"),
            ("cypher", "text/plain"),
        ):
            r = await a.client.get(f"/documents/{doc['id']}/graph.{fmt}")
            assert r.status_code == 200, fmt
            assert r.headers["content-type"].startswith(media)
            disposition = r.headers["content-disposition"]
            assert disposition.startswith("attachment")
            assert f".{fmt}" in disposition
            assert r.content
        r = await a.client.get(f"/documents/{doc['id']}/graph.csv")
        assert r.status_code == 404


async def test_page_png_and_geometry(api: ApiFactory) -> None:  # T-API-10
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.two_pages())
        base = f"/documents/{doc['id']}/pages"
        r = await a.client.get(f"{base}/1.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        for bad in (0, 3):
            assert (await a.client.get(f"{base}/{bad}.png")).status_code == 404
            assert (await a.client.get(f"{base}/{bad}/geometry")).status_code == 404
        g = await a.client.get(f"{base}/2/geometry")
        assert g.status_code == 200
        assert g.headers["cache-control"] == "public, max-age=31536000, immutable"
        words = g.json()
        assert words
        assert set(words[0]) == {"node", "start", "end", "bbox"}
        assert len(words[0]["bbox"]) == 4


async def test_samples_list_samples_only(
    api: ApiFactory, sessions: async_sessionmaker[AsyncSession]
) -> None:  # T-API-11
    async with api() as a:
        await a.upload(pdfs.sectioned())
        async with sessions() as s, s.begin():
            await documents.create(
                s,
                sha256="b" * 64,
                file_name="sample.pdf",
                page_count=2,
                byte_size=100,
                kind="sample",
                expires_at=None,
            )
        r = await a.client.get("/samples")
        assert r.status_code == 200
        items = r.json()["items"]
        assert [d["kind"] for d in items] == ["sample"]
        assert items[0]["file_name"] == "sample.pdf"
        assert items[0]["latest_job"] is None


async def test_why(api: ApiFactory) -> None:  # T-API-12
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        graph = (await a.client.get(f"/documents/{doc['id']}/graph")).json()
        node = graph["nodes"][0]["id"]
        r = await a.client.get(f"/documents/{doc['id']}/why/{node}")
        assert r.status_code == 200
        body = r.json()
        assert body["element"] == node
        assert body["kind"] == "node"
        assert body["maker"]["actor"]
        assert body["statement"]
        assert isinstance(body["ops"], list)
        r = await a.client.get(f"/documents/{doc['id']}/why/no-such-element")
        assert r.status_code == 404
        assert r.json()["error"] == "not_found"


async def test_unknown_job_is_404(api: ApiFactory) -> None:
    async with api() as a:
        r = await a.client.get(f"/jobs/{uuid.uuid4()}")
        assert r.status_code == 404
