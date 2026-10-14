"""Platform wiring: request ids, CORS (spec 07 § 4) and the Prometheus instrumentation."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator

from inkthread.platform.middleware import RequestIdMiddleware
from inkthread.platform.routes import router

CORS_METHODS = ["GET", "POST", "DELETE", "OPTIONS"]
CORS_HEADERS = ["content-type", "x-admin-token", "last-event-id"]
CORS_EXPOSE = ["location", "etag", "retry-after", "x-request-id"]


def install_platform(app: FastAPI, *, cors_origins: list[str]) -> None:
    """Routes and middleware, innermost first: metrics, request ids, then CORS outermost."""
    registry = CollectorRegistry()
    app.state.metrics_registry = registry
    Instrumentator(registry=registry, excluded_handlers=["/metrics"]).instrument(app)
    app.include_router(router)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=CORS_METHODS,
        allow_headers=CORS_HEADERS,
        expose_headers=CORS_EXPOSE,
        allow_credentials=False,
    )
