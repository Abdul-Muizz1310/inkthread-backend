"""Spec 07 § 3 and § 5 event cases (T-API-15…18): replay, resume, no gaps or doubles, 404."""

from __future__ import annotations

import uuid
from typing import Any

import pdfs
import pytest
from apiharness import ApiFactory, parse_sse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.repositories import events
from inkthread.services.broadcast import Broadcast, StreamEvent, Subscription

pytestmark = pytest.mark.integration


async def test_finished_job_replays_everything_then_closes(api: ApiFactory) -> None:  # T-API-15
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        job_id = doc["latest_job"]["id"]
        r = await a.client.get(f"/jobs/{job_id}/events")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache, no-transform"
        assert r.headers["x-accel-buffering"] == "no"
        items = parse_sse(r.text)
        assert [i["id"] for i in items] == list(range(1, len(items) + 1))
        assert items[0]["event"] == "stage"
        assert items[0]["data"]["stage"] == "read"
        assert {i["event"] for i in items} <= {"stage", "delta", "llm", "done"}
        last = items[-1]
        assert last["event"] == "done"
        assert last["data"]["document_id"] == doc["id"]
        graph = (await a.client.get(f"/documents/{doc['id']}/graph")).json()
        assert last["data"]["graph_hash"] == graph["provenance"]["graph_hash"]
        assert set(last["data"]["stats"]) == {"nodes", "edges", "tiers"}


async def test_resume_from_last_event_id(api: ApiFactory) -> None:  # T-API-16
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        url = f"/jobs/{doc['latest_job']['id']}/events"
        full = parse_sse((await a.client.get(url)).text)
        r = await a.client.get(url, headers={"last-event-id": "3"})
        resumed = parse_sse(r.text)
        assert [i["id"] for i in resumed] == [i["id"] for i in full[3:]]
        assert resumed[0]["id"] == 4
        by_query = parse_sse((await a.client.get(url, params={"after": 3})).text)
        assert by_query == resumed
        # Past the end of a finished job: nothing to send, and the stream still closes.
        tail = await a.client.get(url, headers={"last-event-id": str(full[-1]["id"])})
        assert parse_sse(tail.text) == []


async def test_mid_run_stream_has_no_gaps_and_no_doubles(
    api: ApiFactory, sessions: async_sessionmaker[AsyncSession]
) -> None:  # T-API-17
    async with api() as a:
        up = (await a.upload(pdfs.sectioned())).json()
        job_id = uuid.UUID(up["job"]["id"])
        stage: dict[str, Any] = {"stage": "read", "status": "started", "ms": 0}
        async with sessions() as s, s.begin():
            for _ in range(3):
                await events.append(s, job_id, "stage", stage)
        broadcast: Broadcast = a.app.state.services.broadcast
        original = broadcast.subscribe

        def racing_subscribe(jid: uuid.UUID) -> Subscription:
            # The runner persists and publishes while the stream is between subscribe and replay:
            # seq 3 is in the log and live (a double); 4 and 5 are live only (gaps if missed).
            sub = original(jid)
            broadcast.publish(jid, StreamEvent(3, "stage", stage))
            broadcast.publish(jid, StreamEvent(4, "stage", {**stage, "status": "completed"}))
            done = {"document_id": up["document"]["id"], "graph_hash": "0" * 64, "stats": None}
            broadcast.publish(jid, StreamEvent(5, "done", done))
            return sub

        broadcast.subscribe = racing_subscribe  # type: ignore[method-assign]
        items = parse_sse((await a.client.get(f"/jobs/{job_id}/events")).text)
        assert [i["id"] for i in items] == [1, 2, 3, 4, 5]
        assert items[-1]["event"] == "done"
        assert broadcast.subscribers(job_id) == 0


async def test_unknown_job_is_404_before_streaming(api: ApiFactory) -> None:  # T-API-18
    async with api() as a:
        r = await a.client.get(f"/jobs/{uuid.uuid4()}/events")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["error"] == "not_found"


async def test_idle_stream_pings_and_ends_at_its_limit(api: ApiFactory) -> None:
    async with api(ping_interval_s=0.05, stream_max_s=0.4) as a:
        up = (await a.upload(pdfs.sectioned())).json()
        items = parse_sse((await a.client.get(f"/jobs/{up['job']['id']}/events")).text)
        assert items
        assert all(i["event"] == "ping" and i["id"] is None for i in items)
        assert "t" in items[0]["data"]
