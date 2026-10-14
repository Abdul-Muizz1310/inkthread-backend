"""`/health`, `/version` and `/metrics` (spec 10 § 2)."""

from __future__ import annotations

import asyncio
import hmac
import importlib.metadata
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from inkthread import GRAPH_SCHEMA, PIPELINE_VERSION, __version__
from inkthread.core.config import Settings
from inkthread.core.errors import MetricsDisabled, MetricsTokenInvalid, MetricsTokenRequired
from inkthread.schemas.platform import HealthOut, VersionOut

router = APIRouter(tags=["platform"])
DB_TIMEOUT_S = 5.0


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.config.settings
    return settings


async def db_ok(engine: AsyncEngine | None, timeout_s: float = DB_TIMEOUT_S) -> bool:
    """`SELECT 1` within the timeout."""
    if engine is None:
        return False

    async def probe() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(probe(), timeout_s)
    except Exception:  # noqa: BLE001 - any failure means the database is down
        return False
    return True


@router.get("/health", response_model=HealthOut, responses={503: {"model": HealthOut}})
async def health(request: Request) -> JSONResponse:
    settings = _settings(request)
    ok = await db_ok(getattr(request.app.state, "engine", None))
    body = HealthOut(
        status="ok" if ok else "degraded",
        version=__version__,
        commit_sha=settings.commit_sha,
        db="ok" if ok else "down",
    )
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)


@router.get("/version", response_model=VersionOut)
async def version(request: Request) -> VersionOut:
    return VersionOut(
        version=__version__,
        commit_sha=_settings(request).commit_sha,
        pipeline_version=PIPELINE_VERSION,
        inkgrid_version=importlib.metadata.version("inkgrid"),
        graph_schema=GRAPH_SCHEMA,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Response:
    expected = _settings(request).metrics_token
    if expected is None or not expected.get_secret_value():
        raise MetricsDisabled
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise MetricsTokenRequired(headers={"WWW-Authenticate": "Bearer"})
    if not hmac.compare_digest(token.encode(), expected.get_secret_value().encode()):
        raise MetricsTokenInvalid
    registry: CollectorRegistry = request.app.state.metrics_registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
