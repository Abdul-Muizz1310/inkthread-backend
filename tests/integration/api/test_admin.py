"""Spec 07 § 5 admin cases (T-API-13, T-API-14)."""

from __future__ import annotations

from collections.abc import Callable

import pdfs
import pytest
from apiharness import ADMIN, ApiFactory

from inkthread.core.config import Settings

pytestmark = pytest.mark.integration


async def test_delete_needs_the_admin_token(api: ApiFactory) -> None:  # T-API-13
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        url = f"/documents/{doc['id']}"
        r = await a.client.delete(url)
        assert r.status_code == 401
        assert r.json()["error"] == "admin_token_required"
        r = await a.client.delete(url, headers={"x-admin-token": "wrong"})
        assert r.status_code == 403
        assert r.json()["error"] == "admin_token_invalid"
        sha = doc["sha256"]
        assert not (a.upload_root / "pdf" / f"{sha}.pdf").exists()  # processed, not kept
        assert (a.upload_root / "pages" / sha / "1.png").exists()
        assert not (a.blob_root / "pages" / sha).exists()
        r = await a.client.delete(url, headers={"x-admin-token": ADMIN})
        assert r.status_code == 204
        assert (await a.client.get(url)).status_code == 404
        assert not (a.upload_root / "pages" / sha).exists()
        r = await a.client.delete(url, headers={"x-admin-token": ADMIN})
        assert r.status_code == 404


async def test_admin_is_disabled_without_a_configured_token(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:  # T-API-13
    async with api(settings=make_settings(admin_token=None)) as a:
        up = (await a.upload(pdfs.sectioned())).json()
        r = await a.client.delete(
            f"/documents/{up['document']['id']}", headers={"x-admin-token": ADMIN}
        )
        assert r.status_code == 503
        assert r.json()["error"] == "admin_disabled"


async def test_reprocess_makes_a_new_job(api: ApiFactory) -> None:  # T-API-14
    async with api(run_jobs=True) as a:
        # Samples keep their PDF; an upload's is gone once processed (T-PJ-19).
        up = await a.app.state.services.ingest.ingest(pdfs.sectioned(), "s.pdf", kind="sample")
        await a.wait_job(str(up.job.id))
        doc = (await a.client.get(f"/documents/{up.document.id}")).json()
        url = f"/documents/{doc['id']}/reprocess"
        assert (await a.client.post(url)).status_code == 401
        r = await a.client.post(url, headers={"x-admin-token": ADMIN})
        assert r.status_code == 202
        body = r.json()
        assert body["job"]["id"] != doc["latest_job"]["id"]
        assert body["document"]["id"] == doc["id"]
        assert r.headers["location"] == f"/jobs/{body['job']['id']}"
        done = await a.wait_job(body["job"]["id"])
        assert done["status"] == "succeeded"
