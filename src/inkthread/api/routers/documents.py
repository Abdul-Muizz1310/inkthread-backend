"""Document routes (spec 07 § 2): upload, read, graph, exports, pages, why."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, Response
from fastapi.responses import JSONResponse

from inkthread.api.deps import ConfigDep, ServicesDep, rate_key
from inkthread.api.uploads import read_upload
from inkthread.core.errors import RateLimited
from inkthread.domain.why import Why
from inkthread.schemas.documents import DocumentOut, GeometryWord, UploadOut
from inkthread.schemas.platform import ErrorOut
from inkthread.schemas.readings import ReadingOut

router = APIRouter(tags=["documents"])

IMMUTABLE = "public, max-age=31536000, immutable"
GRAPH_CACHE = "public, max-age=300"
ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorOut} for code in (400, 404, 409, 413, 415, 422, 429, 503)
}
Page = Annotated[int, Path(ge=0, le=100_000)]


def upload_response(out: UploadOut) -> JSONResponse:
    """202 with a Location for new work; 200 when the same bytes are already handled."""
    body = out.model_dump(mode="json")
    if out.deduplicated or out.job is None:
        return JSONResponse(body, status_code=200)
    return JSONResponse(body, status_code=202, headers={"Location": f"/jobs/{out.job.id}"})


@router.post(
    "/documents",
    status_code=202,
    response_model=UploadOut,
    responses=ERRORS,
    summary="Upload a PDF (multipart field `file`)",
)
async def upload(request: Request, services: ServicesDep, config: ConfigDep) -> JSONResponse:
    retry = config.limiter.hit(rate_key(request))
    if retry is not None:
        raise RateLimited(headers={"Retry-After": str(retry)}, detail={"retry_after": retry})
    file_name, data = await read_upload(request, config.settings.max_upload_bytes)
    return upload_response(await services.ingest.ingest(data, file_name))


@router.get("/documents/{document_id}", response_model=DocumentOut, responses=ERRORS)
async def get_document(document_id: uuid.UUID, services: ServicesDep) -> DocumentOut:
    return await services.documents.get(document_id)


@router.get("/documents/{document_id}/graph", responses=ERRORS)
async def get_graph(
    document_id: uuid.UUID,
    services: ServicesDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    payload = await services.documents.graph(document_id)
    etag = f'"{payload.graph_hash}"'
    headers = {"ETag": etag, "Cache-Control": GRAPH_CACHE}
    if if_none_match is not None and etag in {t.strip() for t in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)
    return Response(payload.body, media_type="application/json", headers=headers)


@router.get("/documents/{document_id}/reading", response_model=ReadingOut, responses=ERRORS)
async def get_reading(
    document_id: uuid.UUID, services: ServicesDep, response: Response
) -> ReadingOut:
    response.headers["Cache-Control"] = GRAPH_CACHE
    return await services.documents.reading(document_id)


@router.get("/documents/{document_id}/graph.{fmt}", responses=ERRORS)
async def get_export(document_id: uuid.UUID, fmt: str, services: ServicesDep) -> Response:
    export = await services.documents.export(document_id, fmt)
    return Response(
        export.body,
        media_type=export.media_type,
        headers={"Content-Disposition": f'attachment; filename="{export.filename}"'},
    )


@router.get("/documents/{document_id}/pages/{page}.png", responses=ERRORS)
async def get_page(document_id: uuid.UUID, page: Page, services: ServicesDep) -> Response:
    png = await services.documents.page_png(document_id, page)
    return Response(png, media_type="image/png", headers={"Cache-Control": IMMUTABLE})


@router.get(
    "/documents/{document_id}/pages/{page}/geometry",
    response_model=list[GeometryWord],
    responses=ERRORS,
)
async def get_geometry(
    document_id: uuid.UUID, page: Page, services: ServicesDep, response: Response
) -> list[GeometryWord]:
    response.headers["Cache-Control"] = IMMUTABLE
    return await services.documents.page_geometry(document_id, page)


@router.get("/documents/{document_id}/why/{element_id:path}", response_model=Why, responses=ERRORS)
async def get_why(document_id: uuid.UUID, element_id: str, services: ServicesDep) -> Why:
    return await services.documents.why(document_id, element_id)
