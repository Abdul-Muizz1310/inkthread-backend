"""Spec 10 § 5: health, metrics, version (T-OPS-3…6)."""

from __future__ import annotations

from collections.abc import Callable

import inkgrid
import pytest
from apiharness import METRICS, ApiFactory

from inkthread import GRAPH_SCHEMA, PIPELINE_VERSION, __version__
from inkthread.core.config import Settings

pytestmark = pytest.mark.integration


async def test_health_reports_the_database(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:  # T-OPS-3
    async with api() as a:
        r = await a.client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["db"] == "ok"
        assert body["version"] == __version__
        assert "commit_sha" in body
    down = make_settings(database_url="postgresql://u:p@127.0.0.1:1/nothing")
    async with api(settings=down) as a:
        r = await a.client.get("/health")
        assert r.status_code == 503
        assert r.json()["db"] == "down"


async def test_metrics_need_their_token(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:  # T-OPS-4
    async with api(settings=make_settings(metrics_token=None)) as a:
        assert (await a.client.get("/metrics")).status_code == 503
    async with api() as a:
        await a.client.get("/version")
        assert (await a.client.get("/metrics")).status_code == 401
        r = await a.client.get("/metrics", headers={"authorization": "Bearer nope"})
        assert r.status_code == 403
        r = await a.client.get("/metrics", headers={"authorization": f"Bearer {METRICS}"})
        assert r.status_code == 200
        assert "http_request" in r.text


async def test_version(api: ApiFactory) -> None:  # T-OPS-5
    async with api() as a:
        body = (await a.client.get("/version")).json()
        assert body == {
            "version": __version__,
            "commit_sha": body["commit_sha"],
            "pipeline_version": PIPELINE_VERSION,
            "inkgrid_version": inkgrid.__version__,
            "graph_schema": GRAPH_SCHEMA,
        }


async def test_version_reports_the_commit(
    api: ApiFactory, monkeypatch: pytest.MonkeyPatch
) -> None:  # T-OPS-6
    for name in ("COMMIT_SHA", "RENDER_GIT_COMMIT", "GITHUB_SHA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    async with api() as a:
        assert (await a.client.get("/version")).json()["commit_sha"] == "abc123"
        assert (await a.client.get("/health")).json()["commit_sha"] == "abc123"
