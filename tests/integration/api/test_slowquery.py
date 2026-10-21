"""Spec 13: slowquery-detective's per-request receipt (T-SQ-1…3, T-SQ-5) against real Postgres."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pdfs
import pytest
from apiharness import Api, ApiFactory
from sqlalchemy.ext.asyncio import AsyncEngine
from tokens import BASTION, FRONTEND, bastion_token, frontend_token

from inkthread.core.config import Settings
from inkthread.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def keyed(make_settings: Callable[..., Settings]) -> Callable[..., Settings]:
    def make(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "app_env": "development",
            "bastion_signing_key_public": BASTION.spki_b64,
            "inkthread_frontend_signing_key_public": FRONTEND.spki_b64,
        }
        return make_settings(**{**base, **overrides})

    return make


def tok(token: str, rid: str | None = None) -> dict[str, str]:
    headers = {"x-platform-token": token}
    if rid is not None:
        headers["x-request-id"] = rid
    return headers


async def _wait(a: Api, job_id: str) -> dict[str, Any]:
    """Poll a job with a token (the harness's `wait_job` sends none)."""
    async with asyncio.timeout(90):
        while True:
            body: dict[str, Any] = (
                await a.client.get(f"/jobs/{job_id}", headers=tok(frontend_token()))
            ).json()
            if body["status"] in {"succeeded", "failed"}:
                return body
            await asyncio.sleep(0.05)


async def _receipt(client: httpx.AsyncClient, rid: str) -> list[dict[str, Any]]:
    r = await client.get(f"/_slowquery/queries?request_id={rid}", headers=tok(bastion_token()))
    assert r.status_code == 200, r.text
    rows: list[dict[str, Any]] = r.json()
    return rows


async def test_T_SQ_1_a_graph_read_is_listed_under_its_request_id(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(run_jobs=True, settings=keyed()) as a:
        files = {"file": ("r.pdf", pdfs.sectioned(), "application/pdf")}
        up = (await a.client.post("/documents", files=files, headers=tok(frontend_token()))).json()
        job = await _wait(a, up["job"]["id"])
        assert job["status"] == "succeeded"
        doc = up["document"]["id"]
        rid = f"graph-{uuid.uuid4().hex}"
        r = await a.client.get(f"/documents/{doc}/graph", headers=tok(bastion_token(), rid))
        assert r.status_code == 200
        rows = await _receipt(a.client, rid)
        assert rows, "the graph read ran statements"
        assert any("graphs" in row["fingerprint"] for row in rows)
        assert all(row["call_count"] >= 1 for row in rows)
        assert all(row["p50_ms"] is None for row in rows)
        assert await _receipt(a.client, f"other-{uuid.uuid4().hex}") == []


async def test_T_SQ_2_only_bastion_may_read_the_receipt(
    api: ApiFactory, keyed: Callable[..., Settings], make_settings: Callable[..., Settings]
) -> None:
    async with api(settings=keyed()) as a:
        url = "/_slowquery/queries?request_id=x"
        missing = await a.client.get(url)
        assert missing.status_code == 401
        assert missing.json()["detail"] == "missing_platform_token"
        assert (await a.client.get(url, headers=tok(frontend_token()))).status_code == 403
        bad = await a.client.get(url, headers=tok(bastion_token(aud="inkprint")))
        assert bad.status_code == 401
        assert (await a.client.get(url, headers=tok(bastion_token()))).status_code == 200
    async with api(settings=make_settings()) as a:  # test settings: no key, anonymous
        assert (await a.client.get("/_slowquery/queries")).status_code == 403


async def test_T_SQ_3_a_jobs_statements_count_against_the_upload(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    rid = f"upload-{uuid.uuid4().hex}"
    async with api(run_jobs=True, settings=keyed()) as a:
        files = {"file": ("r.pdf", pdfs.ruled_table(), "application/pdf")}
        up = await a.client.post("/documents", files=files, headers=tok(frontend_token(), rid))
        assert up.status_code == 202
        job = await _wait(a, up.json()["job"]["id"])
        assert job["status"] == "succeeded"
        rows = await _receipt(a.client, rid)
    sql = " ".join(row["fingerprint"] for row in rows)
    for table in ("job_events", "graphs", "readings"):
        assert table in sql, table


async def test_T_SQ_5_the_engine_is_built_with_the_app(
    make_settings: Callable[..., Settings],
) -> None:
    for _ in range(2):
        app = create_app(make_settings(), run_jobs=False)
        engine = app.state.engine
        assert isinstance(engine, AsyncEngine)
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            assert app.state.engine is engine
            assert app.state.services.sessions.kw["bind"] is engine
            assert (await client.get("/health")).json()["db"] == "ok"
