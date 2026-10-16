"""Spec 08 § 2: uploads are processed, not kept (T-PJ-19)."""

from __future__ import annotations

import shutil

import pdfs
import pytest
from apiharness import ADMIN, ApiFactory

pytestmark = pytest.mark.integration


async def test_an_upload_whose_files_are_gone_answers_410(api: ApiFactory) -> None:  # T-PJ-19
    async with api(run_jobs=True) as a:
        doc = await a.ready(pdfs.sectioned())
        base = f"/documents/{doc['id']}"
        assert (await a.client.get(f"{base}/pages/1.png")).status_code == 200
        r = await a.client.post(f"{base}/reprocess", headers={"x-admin-token": ADMIN})
        assert r.status_code == 410  # the PDF went when its job ended
        assert r.json()["error"] == "upload_not_kept"
        shutil.rmtree(a.upload_root / "pages" / doc["sha256"])  # a restart lost the rest
        for path in ("pages/1.png", "pages/1/geometry"):
            r = await a.client.get(f"{base}/{path}")
            assert r.status_code == 410
            assert r.json()["error"] == "upload_not_kept"
        assert (await a.client.get(f"{base}/pages/2.png")).status_code == 404  # no such page
        assert (await a.client.get(f"{base}/graph")).status_code == 200
