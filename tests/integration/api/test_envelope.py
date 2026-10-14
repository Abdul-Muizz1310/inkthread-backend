"""Spec 07 § 5 envelope cases (T-API-19…21)."""

from __future__ import annotations

import uuid

import pytest
from apiharness import ApiFactory

pytestmark = pytest.mark.integration


async def test_errors_use_the_envelope_and_500_hides_detail(api: ApiFactory) -> None:  # T-API-19
    async with api(raise_app_exceptions=False) as a:

        async def boom() -> None:
            msg = "secret internals: /etc/passwd"
            raise RuntimeError(msg)

        a.app.add_api_route("/boom", boom)
        for path in (f"/documents/{uuid.uuid4()}", "/documents/x", "/no/such/route"):
            r = await a.client.get(path)
            assert 400 <= r.status_code < 500
            body = r.json()
            assert set(body) == {"error", "message", "detail"}
            assert body["error"]
            assert body["message"]
        r = await a.client.get("/boom")
        assert r.status_code == 500
        body = r.json()
        assert body == {
            "error": "internal_error",
            "message": body["message"],
            "detail": None,
        }
        assert "secret" not in r.text
        assert "Traceback" not in r.text
        assert r.headers["x-request-id"]


async def test_request_ids_are_generated_and_echoed(api: ApiFactory) -> None:  # T-API-20
    async with api() as a:
        r = await a.client.get("/version")
        assert len(r.headers["x-request-id"]) >= 16
        r = await a.client.get("/version", headers={"x-request-id": "abc-123"})
        assert r.headers["x-request-id"] == "abc-123"
        r = await a.client.get(f"/documents/{uuid.uuid4()}", headers={"x-request-id": "e-1"})
        assert r.headers["x-request-id"] == "e-1"
        r = await a.client.get("/version", headers={"x-request-id": "bad id\twith junk" * 20})
        assert r.headers["x-request-id"] != "bad id\twith junk" * 20


async def test_cors_allows_only_configured_origins(api: ApiFactory) -> None:  # T-API-21
    async with api() as a:
        r = await a.client.get("/version", headers={"origin": "http://allowed.example"})
        assert r.headers["access-control-allow-origin"] == "http://allowed.example"
        exposed = r.headers["access-control-expose-headers"].lower()
        for h in ("location", "etag", "retry-after", "x-request-id"):
            assert h in exposed
        pre = await a.client.options(
            "/documents",
            headers={
                "origin": "http://allowed.example",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type, x-admin-token, last-event-id",
            },
        )
        assert pre.status_code == 200
        assert "POST" in pre.headers["access-control-allow-methods"]
        r = await a.client.get("/version", headers={"origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        pre = await a.client.options(
            "/documents",
            headers={"origin": "http://evil.example", "access-control-request-method": "POST"},
        )
        assert "access-control-allow-origin" not in pre.headers
