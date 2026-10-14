"""Helpers for API tests: a running app with a client, and an event-stream parser.

The reader runs in-process (`inproc.read_inprocess`) and the model is a fake, both injected through
`create_app`. `api` builds a client; `run_jobs=True` starts the real `JobRunner`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ADMIN = "admin-secret-token"
METRICS = "metrics-secret-token"


@dataclass
class Api:
    """A running app and a client bound to it."""

    app: Any
    client: httpx.AsyncClient
    blob_root: Path

    async def upload(
        self, data: bytes, name: str = "doc.pdf", *, ip: str | None = None
    ) -> httpx.Response:
        files = {"file": (name, data, "application/pdf")}
        if ip is None:
            return await self.client.post("/documents", files=files)
        transport = httpx.ASGITransport(app=self.app, client=(ip, 4321))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
            return await other.post("/documents", files=files)

    async def wait_job(self, job_id: str, timeout_s: float = 90.0) -> dict[str, Any]:
        async with asyncio.timeout(timeout_s):
            while True:
                r = await self.client.get(f"/jobs/{job_id}")
                body: dict[str, Any] = r.json()
                if body["status"] in {"succeeded", "failed"}:
                    return body
                await asyncio.sleep(0.05)

    async def ready(self, data: bytes, name: str = "doc.pdf") -> dict[str, Any]:
        """Upload and wait until processed; returns the document."""
        r = await self.upload(data, name)
        assert r.status_code in {200, 202}, r.text
        job = await self.wait_job(r.json()["job"]["id"])
        assert job["status"] == "succeeded", job
        doc: dict[str, Any] = (await self.client.get(f"/documents/{job['document_id']}")).json()
        return doc


ApiFactory = Callable[..., AbstractAsyncContextManager[Api]]


def parse_sse(text: str) -> list[dict[str, Any]]:
    """`[{id, event, data}]` from an event-stream body."""
    out: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        item: dict[str, Any] = {"id": None}
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "id":
                item["id"] = int(value)
            elif field == "event":
                item["event"] = value
            elif field == "data":
                item["data"] = json.loads(value)
        out.append(item)
    return out
