"""The FastAPI app: `create_app` wires settings, services, routers and the background workers.

`uvicorn inkthread.main:app` builds the app from the environment on first access, so importing this
module (in tests, say) needs no configuration.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

import httpx
from fastapi import FastAPI

from inkthread import __version__
from inkthread.api.deps import ApiConfig
from inkthread.api.routers import admin, documents, jobs, samples
from inkthread.core.config import Settings, get_settings
from inkthread.core.db import make_engine, make_sessions
from inkthread.core.errors import install_error_handlers
from inkthread.core.logging import configure_logging
from inkthread.core.ratelimit import SlidingWindow
from inkthread.llm.budget import account_remaining_from_openrouter
from inkthread.llm.catalog import ModelCatalog
from inkthread.llm.client import OpenRouterModel
from inkthread.llm.ports import BudgetPort, ModelPort
from inkthread.pipeline.graph import Reader
from inkthread.platform.keys import KeyResolver
from inkthread.platform.setup import install_platform
from inkthread.reader.process import ReadOutcome, read_in_child
from inkthread.services.broadcast import Broadcast
from inkthread.services.container import Services
from inkthread.services.documents import DocumentService
from inkthread.services.ingest import IngestLimits, IngestService
from inkthread.services.llm import AgentSettings, ModelFactory, agent_factory
from inkthread.services.retention import RetentionSweeper
from inkthread.services.runner import JobRunner
from inkthread.services.streams import StreamService
from inkthread.storage.blobs import BlobStore, LocalBlobStore
from inkthread.storage.factory import make_blob_store
from inkthread.storage.stores import Stores

PING_INTERVAL_S = 15.0
STREAM_MAX_S = 600.0
HOUR_S = 3600.0


def child_reader(settings: Settings) -> Reader:
    """The production reader: inkgrid in a spawned child under the read timeout (spec 08 § 3)."""

    async def read(pdf: bytes) -> ReadOutcome:
        return await read_in_child(
            pdf, timeout_s=settings.read_timeout_s, memory_limit_mb=settings.read_memory_limit_mb
        )

    return read


def openrouter_factory(settings: Settings, http: httpx.AsyncClient) -> ModelFactory:
    """OpenRouter for one job's budget."""
    catalog = ModelCatalog(http, settings.openrouter_base_url)
    key = settings.openrouter_api_key

    def build(budget: BudgetPort) -> ModelPort:
        return OpenRouterModel(
            api_key=key.get_secret_value() if key else "",
            base_url=settings.openrouter_base_url,
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
            http=http,
            catalog=catalog,
            budget=budget,
            max_tokens=settings.llm_max_tokens,
            timeout_s=settings.llm_timeout_s,
        )

    return build


def create_app(
    settings: Settings | None = None,
    *,
    reader: Reader | None = None,
    model: ModelPort | None = None,
    blobs: BlobStore | None = None,
    run_jobs: bool = True,
    ping_interval_s: float = PING_INTERVAL_S,
    stream_max_s: float = STREAM_MAX_S,
) -> FastAPI:
    """Build the app.

    `reader`, `model` and `blobs` (the samples' store) replace the production adapters (tests pass
    the in-process reader and a fake model). Uploads always go to `UPLOAD_ROOT` (spec 08 § 2).
    `run_jobs=False` leaves the job runner and the sweep off.
    """
    cfg = settings or get_settings()
    configure_logging(level=cfg.log_level, json_logs=cfg.is_production)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(cfg.database_url)
        sessions = make_sessions(engine)
        stores = Stores(
            samples=blobs or make_blob_store(cfg, sessions),
            uploads=LocalBlobStore(cfg.upload_root),
        )
        http = httpx.AsyncClient()
        key = cfg.openrouter_api_key

        async def account_remaining() -> int | None:
            if key is None:
                return None
            return await account_remaining_from_openrouter(
                http, cfg.openrouter_base_url, key.get_secret_value()
            )

        def fixed_model(_budget: BudgetPort) -> ModelPort:
            assert model is not None  # noqa: S101 - only used when a model was injected
            return model

        broadcast = Broadcast()
        runner = JobRunner(
            sessions=sessions,
            stores=stores,
            broadcast=broadcast,
            agents=agent_factory(
                sessions,
                AgentSettings(
                    mode=cfg.llm_mode,
                    primary=cfg.openrouter_model_primary,
                    fast=cfg.openrouter_model_fast,
                    fallback=cfg.openrouter_model_fallback,
                    per_document=cfg.llm_max_requests_per_document,
                    daily_cap=cfg.llm_daily_request_cap,
                    reserve=cfg.llm_account_reserve,
                    max_tokens=cfg.llm_max_tokens,
                ),
                model=fixed_model if model is not None else openrouter_factory(cfg, http),
                account_remaining=account_remaining,
            ),
            reader=reader or child_reader(cfg),
            inkgrid_version=importlib.metadata.version("inkgrid"),
            job_timeout_s=cfg.job_timeout_s,
            sample_llm_mode=cfg.sample_llm_mode,
        )
        services = Services(
            sessions=sessions,
            broadcast=broadcast,
            ingest=IngestService(
                sessions,
                stores,
                limits=IngestLimits(
                    max_pages=cfg.max_pages,
                    max_queue=cfg.max_queue,
                    upload_ttl=dt.timedelta(minutes=cfg.upload_ttl_minutes),
                ),
                wake=runner.wake,
            ),
            documents=DocumentService(sessions, stores, wake=runner.wake),
            streams=StreamService(sessions, broadcast),
            runner=runner,
            retention=RetentionSweeper(sessions, stores),
        )
        app.state.engine = engine
        app.state.services = services
        if run_jobs:
            await runner.start()
            await services.retention.start()
        try:
            yield
        finally:
            await runner.stop()
            await services.retention.stop()
            await http.aclose()
            await engine.dispose()

    app = FastAPI(
        title="inkthread",
        version=__version__,
        summary="A born-digital PDF as a knowledge graph of its parts and their threads.",
        lifespan=lifespan,
    )
    app.state.config = ApiConfig(
        settings=cfg,
        limiter=SlidingWindow(limit=cfg.uploads_per_hour, window_s=HOUR_S),
        ping_interval_s=ping_interval_s,
        stream_max_s=stream_max_s,
    )
    install_error_handlers(app)
    for module in (documents, jobs, samples, admin):
        app.include_router(module.router)
    install_platform(
        app,
        cors_origins=cfg.cors_origins,
        keys=KeyResolver(
            bastion=cfg.bastion_signing_key_public,
            bastion_url=cfg.bastion_public_key_url,
            frontend=cfg.inkthread_frontend_signing_key_public,
        ),
        demo_mode=cfg.demo_mode,
        enforce_unconfigured=cfg.app_env != "test",
    )
    return app


@lru_cache(maxsize=1)
def _default_app() -> FastAPI:
    return create_app()


def __getattr__(name: str) -> FastAPI:
    """`inkthread.main:app`, built from the environment on first access."""
    if name == "app":
        return _default_app()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
