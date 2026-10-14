"""The curated samples (spec 07 § 2). Uploads are never listed."""

from __future__ import annotations

from fastapi import APIRouter

from inkthread.api.deps import ServicesDep
from inkthread.schemas.documents import SamplesOut

router = APIRouter(tags=["samples"])


@router.get("/samples", response_model=SamplesOut)
async def list_samples(services: ServicesDep) -> SamplesOut:
    return SamplesOut(items=await services.documents.samples())
