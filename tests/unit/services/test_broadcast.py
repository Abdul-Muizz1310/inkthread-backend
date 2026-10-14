"""The in-process broadcast and the event stream's merge of replay and live (spec 07 § 3)."""

from __future__ import annotations

import uuid

from inkthread.services.broadcast import Broadcast, StreamEvent


async def test_subscribers_get_published_events_until_they_close() -> None:
    b = Broadcast()
    job = uuid.uuid4()
    other = uuid.uuid4()
    a = b.subscribe(job)
    c = b.subscribe(job)
    b.publish(job, StreamEvent(1, "stage", {"x": 1}))
    b.publish(other, StreamEvent(1, "stage", {"x": 2}))
    assert a.queue.get_nowait() == StreamEvent(1, "stage", {"x": 1})
    assert c.queue.get_nowait().seq == 1
    assert a.queue.empty()
    assert b.subscribers(job) == 2
    a.close()
    c.close()
    a.close()
    assert b.subscribers(job) == 0
    b.publish(job, StreamEvent(2, "stage", {}))  # nobody listens: dropped


async def test_terminal_events() -> None:
    assert StreamEvent(1, "done", {}).terminal
    assert StreamEvent(1, "failed", {}).terminal
    assert not StreamEvent(1, "stage", {}).terminal
