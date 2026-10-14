"""Server-sent events for a job (spec 07 § 3): `id:` is the seq, pings every 15 s, 10 min max."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from inkthread.services.broadcast import StreamEvent
from inkthread.services.streams import EventStream

HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


def format_event(event: StreamEvent) -> str:
    """One persisted event as an SSE block."""
    data = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"


def format_ping() -> str:
    """A keep-alive; never persisted, so it has no id."""
    return f"event: ping\ndata: {json.dumps({'t': int(time.time())})}\n\n"


def parse_resume(last_event_id: str | None, after: int | None) -> int:
    """`Last-Event-ID` wins over `?after=`; anything unparsable means from the start."""
    if last_event_id is not None and last_event_id.strip().isdigit():
        return int(last_event_id.strip())
    return after or 0


async def _body(stream: EventStream, ping_s: float, max_s: float) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    end = loop.time() + max_s
    try:
        while not stream.ended:
            remaining = end - loop.time()
            if remaining <= 0:
                break
            event = await stream.next(min(ping_s, remaining))
            if event is not None:
                yield format_event(event)
            elif loop.time() < end:
                yield format_ping()
    finally:
        stream.close()


def event_response(stream: EventStream, *, ping_s: float, max_s: float) -> StreamingResponse:
    """Stream until the terminal event, or until `max_s` (the client resumes with Last-Event-ID)."""
    return StreamingResponse(
        _body(stream, ping_s, max_s), media_type="text/event-stream", headers=HEADERS
    )
