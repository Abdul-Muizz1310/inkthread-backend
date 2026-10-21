"""Spec 12 § 4 through the real app: conformance cases 1, 2, 10-14, and T-PT-15…19."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import httpx
import pdfs
import pytest
from apiharness import ADMIN, METRICS, Api, ApiFactory, parse_sse
from structlog.testing import capture_logs
from tokens import BASTION, FRONTEND, bastion_token, frontend_token

from inkthread.core.config import Settings

pytestmark = pytest.mark.integration

ORIGIN = "http://allowed.example"


@pytest.fixture
def keyed(make_settings: Callable[..., Settings]) -> Callable[..., Settings]:
    """Production-like settings: both keys trusted, the test exemption off."""

    def make(**overrides: object) -> Settings:
        base: dict[str, object] = {
            "app_env": "development",
            "bastion_signing_key_public": BASTION.spki_b64,
            "inkthread_frontend_signing_key_public": FRONTEND.spki_b64,
        }
        return make_settings(**{**base, **overrides})

    return make


def tok(token: str) -> dict[str, str]:
    return {"x-platform-token": token}


async def test_T_PT_1_and_2_tokens_through_the_app(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed()) as a:
        assert (await a.client.get("/samples", headers=tok(bastion_token()))).status_code == 200
        assert (await a.client.get("/samples", headers=tok(frontend_token()))).status_code == 200
        bearer = {"authorization": f"Bearer {bastion_token()}"}
        assert (await a.client.get("/samples", headers=bearer)).status_code == 200
        r = await a.client.get("/samples", headers=tok(bastion_token(aud="inkprint")))
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid_platform_token"
        assert r.json()["error"] == "invalid_platform_token"


async def test_T_PT_10_a_missing_token_is_401_unless_demo_mode(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed()) as a:
        r = await a.client.get("/samples")
        assert r.status_code == 401
        assert r.json()["detail"] == "missing_platform_token"
    async with api(settings=keyed(demo_mode=True)) as a:
        with capture_logs() as logs:
            r = await a.client.get("/samples")
        assert r.status_code == 200
        assert any(
            e["log_level"] == "warning" and e["event"] == "platform_token_missing" for e in logs
        )


async def test_T_PT_11_demo_mode_never_excuses_a_bad_token(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed(demo_mode=True)) as a:
        r = await a.client.get("/samples", headers=tok(bastion_token(aud="magpie")))
        assert r.status_code == 401
        assert r.json()["detail"] == "invalid_platform_token"


async def test_T_PT_12_no_trusted_key_fails_closed(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:
    for demo in (False, True):
        async with api(settings=make_settings(app_env="development", demo_mode=demo)) as a:
            r = await a.client.get("/samples", headers=tok(bastion_token()))
            assert r.status_code == 503
            assert r.json()["detail"] == "platform_auth_unconfigured"
            assert (await a.client.get("/health")).status_code == 200


async def test_T_PT_13_public_routes_need_no_token_and_no_write_is_public(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed()) as a:
        for path in ("/health", "/version", "/openapi.json", "/docs", "/redoc"):
            r = await a.client.get(path)
            assert r.status_code == 200, path
        r = await a.client.get("/metrics", headers={"authorization": f"Bearer {METRICS}"})
        assert r.status_code == 200
        doc = uuid.uuid4()
        writes = [
            ("POST", "/documents"),
            ("POST", f"/documents/{doc}/reprocess"),
            ("DELETE", f"/documents/{doc}"),
        ]
        for method, path in writes:
            r = await a.client.request(method, path, headers={"x-admin-token": ADMIN})
            assert r.status_code == 401, (method, path)
        reads = [
            "/samples",
            f"/documents/{doc}",
            f"/documents/{doc}/graph",
            f"/documents/{doc}/reading",
            f"/documents/{doc}/pages/1.png",
            f"/jobs/{doc}",
            f"/jobs/{doc}/events",
            "/documents-not-docs",
            "/docsx",
        ]
        for path in reads:
            assert (await a.client.get(path)).status_code == 401, path


async def _upload(a: Api, token: str, ip: str, name: str = "a.pdf") -> int:
    """Upload from client address `ip`, as uvicorn's proxy headers set it behind Render."""
    transport = httpx.ASGITransport(app=a.app, client=(ip, 4321))
    files = {"file": (name, pdfs.sectioned(), "application/pdf")}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/documents", files=files, headers=tok(token))
    return r.status_code


async def test_T_PT_14_two_visitors_through_the_frontend_get_two_buckets(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed(uploads_per_hour=2)) as a:
        for _ in range(2):
            assert await _upload(a, frontend_token(), "203.0.113.7") in {200, 202}
        assert await _upload(a, frontend_token(), "203.0.113.7") == 429
        # Another visitor of the same site: same iss and sub, another address.
        assert await _upload(a, frontend_token(), "198.51.100.2") in {200, 202}
        # The first visitor's bastion uploads keep their own bucket, keyed on the pseudonym.
        assert await _upload(a, bastion_token(sub="v_aaaaaaaaaa"), "203.0.113.7") in {200, 202}


async def test_T_PT_14_bastion_buckets_follow_the_pseudonym_not_the_address(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed(uploads_per_hour=1)) as a:
        ip = "192.0.2.1"
        assert await _upload(a, bastion_token(sub="v_aaaaaaaaaa"), ip) in {200, 202}
        assert await _upload(a, bastion_token(sub="v_aaaaaaaaaa"), "192.0.2.99") == 429
        assert await _upload(a, bastion_token(sub="v_bbbbbbbbbb"), ip) in {200, 202}


async def test_T_PT_15_a_refusal_names_the_check_and_never_the_token(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    bad = bastion_token(aud="paper-trail")
    async with api(settings=keyed()) as a:
        with capture_logs() as logs:
            await a.client.get("/samples", headers=tok(bad))
    (entry,) = [e for e in logs if e["event"] == "platform_token_rejected"]
    assert entry["log_level"] == "warning"
    assert entry["check"] == "aud"
    assert bad not in repr(logs)


async def test_T_PT_16_admin_routes_need_both_tokens(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    doc = uuid.uuid4()
    async with api(settings=keyed()) as a:
        r = await a.client.delete(f"/documents/{doc}", headers={"x-admin-token": ADMIN})
        assert r.status_code == 401
        r = await a.client.delete(f"/documents/{doc}", headers=tok(bastion_token()))
        assert r.status_code == 401
        assert r.json()["error"] == "admin_token_required"
        both = {**tok(bastion_token()), "x-admin-token": ADMIN}
        assert (await a.client.delete(f"/documents/{doc}", headers=both)).status_code == 404


async def test_T_PT_18_cors_allows_the_token_header_and_covers_refusals(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(settings=keyed()) as a:
        pre = await a.client.options(
            "/samples",
            headers={
                "origin": ORIGIN,
                "access-control-request-method": "GET",
                "access-control-request-headers": "x-platform-token, x-request-id",
            },
        )
        assert pre.status_code == 200
        allowed = pre.headers["access-control-allow-headers"].lower()
        assert "x-platform-token" in allowed
        assert "x-request-id" in allowed
        r = await a.client.get("/samples", headers={"origin": ORIGIN})
        assert r.status_code == 401
        assert r.headers["access-control-allow-origin"] == ORIGIN
        assert r.headers["x-request-id"]


async def test_T_PT_19_the_stream_and_the_reads_work_with_a_token(
    api: ApiFactory, keyed: Callable[..., Settings]
) -> None:
    async with api(run_jobs=True, settings=keyed()) as a:
        headers = tok(frontend_token())
        files = {"file": ("r.pdf", pdfs.ruled_table(), "application/pdf")}
        up = (await a.client.post("/documents", files=files, headers=headers)).json()
        stream = await a.client.get(
            f"/jobs/{up['job']['id']}/events", headers=tok(frontend_token())
        )
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert parse_sse(stream.text)[-1]["event"] == "done"
        doc = up["document"]["id"]
        for path in (f"/documents/{doc}/graph", f"/documents/{doc}/reading"):
            assert (await a.client.get(path, headers=tok(frontend_token()))).status_code == 200
            assert (await a.client.get(path)).status_code == 401
        png = await a.client.get(f"/documents/{doc}/pages/1.png", headers=tok(frontend_token()))
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
