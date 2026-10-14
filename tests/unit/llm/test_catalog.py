"""Spec 05 § 6: the model catalogue decides the response format."""

from __future__ import annotations

import httpx
import respx

from inkthread.llm.catalog import Capabilities, ModelCatalog

BASE = "https://openrouter.test/api/v1"


@respx.mock
async def test_capabilities_are_read_and_cached() -> None:
    route = respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "a/x",
                        "supported_parameters": ["structured_outputs", "response_format"],
                    },
                    {"id": "b/y", "supported_parameters": None},
                ]
            },
        )
    )
    now = [0.0]
    async with httpx.AsyncClient() as http:
        catalog = ModelCatalog(http, BASE, clock=lambda: now[0])
        assert await catalog.capabilities("a/x") == Capabilities(True, True)
        assert await catalog.capabilities("b/y") == Capabilities(False, False)
        assert await catalog.capabilities("c/unknown") == Capabilities(False, False)
        assert route.call_count == 1
        assert "authorization" not in route.calls[0].request.headers
        now[0] = 24 * 3600 + 1
        await catalog.capabilities("a/x")
        assert route.call_count == 2


@respx.mock
async def test_fetch_failure_means_no_capabilities() -> None:
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(503))
    async with httpx.AsyncClient() as http:
        catalog = ModelCatalog(http, BASE)
        assert await catalog.capabilities("a/x") == Capabilities(False, False)
    respx.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"oops": 1}))
    async with httpx.AsyncClient() as http:
        assert await ModelCatalog(http, BASE).capabilities("a/x") == Capabilities(False, False)
