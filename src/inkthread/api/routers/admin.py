"""Admin routes behind X-Admin-Token (spec 07 § 2): delete and reprocess a document."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from inkthread.api.deps import AdminDep, ServicesDep
from inkthread.api.routers.documents import upload_response
from inkthread.schemas.documents import UploadOut
from inkthread.schemas.platform import ErrorOut

router = APIRouter(tags=["admin"], dependencies=[AdminDep])
ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorOut} for code in (401, 403, 404, 503)
}


@router.delete("/documents/{document_id}", status_code=204, responses=ERRORS)
async def delete_document(document_id: uuid.UUID, services: ServicesDep) -> Response:
    await services.documents.delete(document_id)
    return Response(status_code=204)


@router.post(
    "/documents/{document_id}/reprocess",
    status_code=202,
    response_model=UploadOut,
    responses=ERRORS,
)
async def reprocess(document_id: uuid.UUID, services: ServicesDep) -> JSONResponse:
    return upload_response(await services.documents.reprocess(document_id))
