"""Job routes (spec 07 § 2, § 3): status and the event stream."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from inkthread.api.deps import ConfigDep, ServicesDep
from inkthread.api.sse import event_response, parse_resume
from inkthread.schemas.jobs import JobOut
from inkthread.schemas.platform import ErrorOut

router = APIRouter(tags=["jobs"])
ERRORS: dict[int | str, dict[str, object]] = {404: {"model": ErrorOut}, 422: {"model": ErrorOut}}


@router.get("/jobs/{job_id}", response_model=JobOut, responses=ERRORS)
async def get_job(job_id: uuid.UUID, services: ServicesDep) -> JobOut:
    return await services.documents.job(job_id)


@router.get(
    "/jobs/{job_id}/events",
    responses={**ERRORS, 200: {"content": {"text/event-stream": {}}}},
    response_class=StreamingResponse,
)
async def job_events(
    job_id: uuid.UUID,
    services: ServicesDep,
    config: ConfigDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    stream = await services.streams.open(job_id, parse_resume(last_event_id, after))
    return event_response(stream, ping_s=config.ping_interval_s, max_s=config.stream_max_s)
