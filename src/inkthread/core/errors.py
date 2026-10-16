"""Domain errors and the error envelope (spec 07 § 1).

Every error body is `{"error": code, "message": one sentence, "detail": object | null}`. A
`DomainError` carries its status and code; services raise them and never see HTTP. The handlers
installed by `install_error_handlers` turn them, FastAPI's validation errors and anything
unexpected into the envelope.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_log = structlog.get_logger(__name__)

#: A JSON object carried in an envelope's `detail`.
JsonObject = dict[str, Any]


class DomainError(Exception):
    """An expected failure with an HTTP status and a stable code."""

    status: ClassVar[int] = 400
    code: ClassVar[str] = "bad_request"
    default_message: ClassVar[str] = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: JsonObject | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.detail = detail
        self.headers: dict[str, str] = dict(headers or {})
        super().__init__(self.message)


class EmptyFile(DomainError):
    status, code = 400, "empty_file"
    default_message = "The upload has no bytes."


class AdminTokenRequired(DomainError):
    status, code = 401, "admin_token_required"
    default_message = "This route needs the X-Admin-Token header."


class AdminTokenInvalid(DomainError):
    status, code = 403, "admin_token_invalid"
    default_message = "The admin token is wrong."


class NotFound(DomainError):
    status, code = 404, "not_found"
    default_message = "Nothing exists here."


class GraphNotReady(DomainError):
    status, code = 409, "graph_not_ready"
    default_message = "The graph is not ready yet; wait for the job to finish."


class UploadNotKept(DomainError):
    status, code = 410, "upload_not_kept"
    default_message = (
        "Uploads are processed, not kept, and this one's files are gone; upload it again."
    )


class FileTooLarge(DomainError):
    status, code = 413, "file_too_large"
    default_message = "The upload is larger than the limit."


class NotAPdf(DomainError):
    status, code = 415, "not_a_pdf"
    default_message = "The upload is not a PDF: no %PDF- marker in its first 1,024 bytes."


class PdfUnreadable(DomainError):
    status, code = 422, "pdf_unreadable"
    default_message = "The PDF cannot be opened."


class PdfEncrypted(DomainError):
    status, code = 422, "pdf_encrypted"
    default_message = "The PDF needs a password to open."


class TooManyPages(DomainError):
    status, code = 422, "too_many_pages"
    default_message = "The PDF has more pages than the limit."


class RateLimited(DomainError):
    status, code = 429, "rate_limited"
    default_message = "Too many uploads from this address; try again later."


class QueueFull(DomainError):
    status, code = 503, "queue_full"
    default_message = "The processing queue is full; try again in a few minutes."


class AdminDisabled(DomainError):
    status, code = 503, "admin_disabled"
    default_message = "Admin routes are disabled: no admin token is configured."


class MetricsDisabled(DomainError):
    status, code = 503, "metrics_disabled"
    default_message = "Metrics are disabled: no metrics token is configured."


class MetricsTokenRequired(DomainError):
    status, code = 401, "metrics_token_required"
    default_message = "Metrics need an Authorization: Bearer token."


class MetricsTokenInvalid(DomainError):
    status, code = 403, "metrics_token_invalid"
    default_message = "The metrics token is wrong."


class ServiceUnavailable(DomainError):
    status, code = 503, "service_unavailable"
    default_message = "The service cannot reach its database."


def envelope(code: str, message: str, detail: object = None) -> JsonObject:
    """The error body."""
    return {"error": code, "message": message, "detail": detail}


_HTTP_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "file_too_large",
}


def _request_id(request: Request) -> dict[str, str]:
    rid = getattr(request.state, "request_id", None)
    return {"x-request-id": rid} if isinstance(rid, str) else {}


async def _domain(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)  # noqa: S101 - registered for DomainError only
    return JSONResponse(
        envelope(exc.code, exc.message, exc.detail),
        status_code=exc.status,
        headers={**exc.headers, **_request_id(request)},
    )


async def _validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered for it only
    errors = jsonable_encoder(exc.errors(), exclude={"input", "ctx", "url"})
    return JSONResponse(
        envelope("validation_error", "The request is not valid.", {"errors": errors}),
        status_code=422,
        headers=_request_id(request),
    )


async def _http(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - registered for it only
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    message = exc.detail or "Request failed."
    return JSONResponse(
        envelope(code, message),
        status_code=exc.status_code,
        headers={**(exc.headers or {}), **_request_id(request)},
    )


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    _log.error("unhandled_error", path=request.url.path, error=type(exc).__name__, exc_info=exc)
    return JSONResponse(
        envelope("internal_error", "Something went wrong on our side."),
        status_code=500,
        headers=_request_id(request),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Map every failure to the envelope."""
    app.add_exception_handler(DomainError, _domain)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(Exception, _unexpected)
