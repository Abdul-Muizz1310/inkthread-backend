"""Structured logs (spec 10 § 2): JSON in production, console otherwise, with the request id."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, level: str, json_logs: bool) -> None:
    """Configure structlog and the standard library's root logger once per process."""
    numeric = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if json_logs:
        processors.append(structlog.processors.format_exc_info)
    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
        cache_logger_on_first_use=False,
    )
    logging.basicConfig(level=numeric, stream=sys.stderr, format="%(message)s", force=False)


def bind_request_id(request_id: str) -> None:
    """Bind the request id to every log line of the current request."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
