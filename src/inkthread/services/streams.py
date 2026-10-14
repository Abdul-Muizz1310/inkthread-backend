"""A job's event stream: replay the persisted log, then follow live events (spec 07 § 3).

No gaps, no doubles: the stream subscribes to the broadcast **before** it reads the log, so an event
persisted in between is in the log, the live queue, or both; anything at or below the last id sent
is dropped. A finished job's stream ends after its log.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core.errors import NotFound
from inkthread.repositories import events, jobs
from inkthread.services.broadcast import Broadcast, StreamEvent, Subscription

FINISHED = frozenset({"succeeded", "failed"})


class EventStream:
    """Yields each event once, in order; `next` returns None when `timeout` passes quietly."""

    def __init__(
        self, sub: Subscription, replay: list[StreamEvent], after: int, *, finished: bool
    ) -> None:
        self._sub = sub
        self._pending = deque(replay)
        self._last = after
        self._ended = finished and not any(e.terminal for e in replay)
        self._closed = False

    @property
    def ended(self) -> bool:
        """Whether the terminal event was sent (or the job had finished before the stream)."""
        return self._ended

    async def next(self, timeout: float) -> StreamEvent | None:
        """The next unsent event, or None after `timeout` seconds without one."""
        if self._ended:
            msg = "the stream has ended; check `ended` before asking for more"
            raise RuntimeError(msg)
        while self._pending:
            event = self._pending.popleft()
            if event.seq > self._last:
                return self._sent(event)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                event = await asyncio.wait_for(self._sub.queue.get(), remaining)
            except TimeoutError:
                return None
            if event.seq > self._last:
                return self._sent(event)

    def _sent(self, event: StreamEvent) -> StreamEvent:
        self._last = event.seq
        if event.terminal:
            self._ended = True
        return event

    def close(self) -> None:
        """Unsubscribe."""
        if not self._closed:
            self._closed = True
            self._sub.close()


class StreamService:
    """Opens event streams; a missing job raises `NotFound` before anything is sent."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], broadcast: Broadcast) -> None:
        self._sessions = sessions
        self._broadcast = broadcast

    async def open(self, job_id: uuid.UUID, after: int) -> EventStream:
        """Subscribe, then read the log after `after`."""
        sub = self._broadcast.subscribe(job_id)
        try:
            async with self._sessions() as s:
                job = await jobs.get(s, job_id)
                finished = job is not None and job.status in FINISHED
                rows = await events.after(s, job_id, after) if job is not None else []
        except BaseException:
            sub.close()
            raise
        if job is None:
            sub.close()
            raise NotFound(f"No job {job_id}.")
        replay = [StreamEvent(r.seq, r.type, r.payload) for r in rows]
        return EventStream(sub, replay, after, finished=finished)
