"""The API under test: a real app (lifespan, Postgres, local blobs) through httpx's ASGI transport.

The reader runs in-process (`inproc.read_inprocess`) and the model is a fake, both injected through
`create_app`. `api(run_jobs=True)` starts the real `JobRunner`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from apiharness import ADMIN, METRICS, Api, ApiFactory
from inproc import read_inprocess

from inkthread.core.config import Settings
from inkthread.llm.ports import ModelPort
from inkthread.main import create_app
from inkthread.pipeline.graph import Reader


@pytest.fixture
def make_settings(database_url: str, tmp_path: Path) -> Callable[..., Settings]:
    def make(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "app_env": "test",
            "database_url": database_url,
            "llm_mode": "off",
            "blob_root": tmp_path / "blobs",
            "upload_root": tmp_path / "uploads",
            "uploads_per_hour": 1000,
            "admin_token": ADMIN,
            "metrics_token": METRICS,
            "cors_origins": "http://allowed.example",
        }
        return Settings(_env_file=None, **{**base, **overrides})

    return make


@pytest.fixture
def api(make_settings: Callable[..., Settings]) -> ApiFactory:
    @asynccontextmanager
    async def build(
        *,
        run_jobs: bool = False,
        reader: Reader = read_inprocess,
        model: ModelPort | None = None,
        raise_app_exceptions: bool = True,
        settings: Settings | None = None,
        **app_kw: Any,
    ) -> AsyncIterator[Api]:
        s = settings or make_settings()
        app = create_app(s, reader=reader, model=model, run_jobs=run_jobs, **app_kw)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        ):
            yield Api(app=app, client=client, blob_root=s.blob_root, upload_root=s.upload_root)

    return build
