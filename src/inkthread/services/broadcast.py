"""In-process pub/sub of a job's live events (spec 07 § 3).

The runner publishes an event only after it is persisted, so a stream that subscribes before it
reads the log sees every event at least once, and drops by sequence number what it has already sent.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

#: An event's JSON payload, exactly as persisted in `job_events.payload`.
EventData = dict[str, Any]

TERMINAL = frozenset({"done", "failed"})


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One persisted event: its sequence number (from 1), its name and its payload."""

    seq: int
    type: str
    data: EventData

    @property
    def terminal(self) -> bool:
        """Whether the job ends with this event."""
        return self.type in TERMINAL


@dataclass
class Subscription:
    """One listener's queue; `close` it when done."""

    job_id: uuid.UUID
    owner: Broadcast
    queue: asyncio.Queue[StreamEvent] = field(default_factory=asyncio.Queue)

    def close(self) -> None:
        """Stop receiving; closing twice is harmless."""
        self.owner.unsubscribe(self)


class Broadcast:
    """Subscribers by job. Queues are unbounded: a job emits a bounded number of events."""

    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[int]] = {}
        self._by_id: dict[int, Subscription] = {}

    def subscribe(self, job_id: uuid.UUID) -> Subscription:
        """Start receiving a job's live events."""
        sub = Subscription(job_id=job_id, owner=self)
        self._subs.setdefault(job_id, set()).add(id(sub))
        self._by_id[id(sub)] = sub
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Stop a subscription."""
        ids = self._subs.get(sub.job_id)
        if ids is None or id(sub) not in ids:
            return
        ids.discard(id(sub))
        self._by_id.pop(id(sub), None)
        if not ids:
            del self._subs[sub.job_id]

    def publish(self, job_id: uuid.UUID, event: StreamEvent) -> None:
        """Hand an already-persisted event to every current subscriber of its job."""
        for key in tuple(self._subs.get(job_id, ())):
            self._by_id[key].queue.put_nowait(event)

    def subscribers(self, job_id: uuid.UUID) -> int:
        """How many listen to a job."""
        return len(self._subs.get(job_id, ()))
