"""Spec 07 § 5 upload cases (T-API-1…6) and the duplicate-while-running review item."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable

import pdfs
import pymupdf
import pytest
from apiharness import ApiFactory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inkthread.core.config import Settings
from inkthread.repositories import documents, jobs

pytestmark = pytest.mark.integration


def many_pages(n: int) -> bytes:
    doc = pymupdf.open()
    for i in range(n):
        doc.new_page().insert_text((72, 72), f"page {i + 1}", fontsize=10)
    data: bytes = doc.tobytes()
    return data


async def test_valid_pdf_is_accepted_and_queued(api: ApiFactory) -> None:  # T-API-1
    async with api() as a:
        r = await a.upload(pdfs.sectioned(), "rules.pdf")
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["deduplicated"] is False
        doc, job = body["document"], body["job"]
        assert r.headers["location"] == f"/jobs/{job['id']}"
        assert job["status"] == "queued"
        assert job["document_id"] == doc["id"]
        assert job["error"] is None
        assert job["llm"] == {"requests": 0, "cached": 0, "failed": 0, "rejected": 0}
        assert job["stages"] == []
        assert doc["kind"] == "upload"
        assert doc["status"] == "queued"
        assert doc["file_name"] == "rules.pdf"
        assert doc["page_count"] == 1
        assert doc["stats"] is None
        assert doc["expires_at"] is not None
        assert doc["latest_job"]["id"] == job["id"]
        assert len(doc["sha256"]) == 64
        stored = a.blob_root / "pdf" / f"{doc['sha256']}.pdf"
        assert stored.read_bytes() == pdfs.sectioned()


async def test_same_bytes_are_deduplicated(api: ApiFactory) -> None:  # T-API-2
    async with api() as a:
        first = (await a.upload(pdfs.sectioned())).json()
        r = await a.upload(pdfs.sectioned(), "again.pdf")
        assert r.status_code == 200
        body = r.json()
        assert body["deduplicated"] is True
        assert body["document"]["id"] == first["document"]["id"]
        assert body["job"]["id"] == first["job"]["id"]


async def test_after_a_failed_job_the_same_bytes_requeue(
    api: ApiFactory, sessions: async_sessionmaker[AsyncSession]
) -> None:  # T-API-3
    async with api() as a:
        first = (await a.upload(pdfs.sectioned())).json()
        job_id = uuid.UUID(first["job"]["id"])
        async with sessions() as s, s.begin():
            await jobs.finish(
                s, job_id, status="failed", stages=[], llm={}, error_code="x", error_message="y"
            )
            await documents.set_status(s, uuid.UUID(first["document"]["id"]), "failed")
        r = await a.upload(pdfs.sectioned())
        assert r.status_code == 202
        body = r.json()
        assert body["deduplicated"] is False
        assert body["document"]["id"] == first["document"]["id"]
        assert body["job"]["id"] != first["job"]["id"]
        assert body["document"]["status"] == "queued"


async def test_duplicate_upload_while_running(
    api: ApiFactory, sessions: async_sessionmaker[AsyncSession]
) -> None:  # review focus 4
    async with api() as a:
        first = (await a.upload(pdfs.sectioned())).json()
        async with sessions() as s, s.begin():
            claimed = await jobs.claim_next(s)
        assert claimed is not None
        assert str(claimed.id) == first["job"]["id"]
        r = await a.upload(pdfs.sectioned())
        assert r.status_code == 200
        assert r.json()["job"]["id"] == first["job"]["id"]
        assert r.json()["job"]["status"] == "running"
        async with sessions() as s:
            assert await jobs.count_queued(s) == 0


async def test_concurrent_first_uploads_share_one_job(api: ApiFactory) -> None:
    async with api() as a:
        r1, r2 = await asyncio.gather(a.upload(pdfs.two_pages()), a.upload(pdfs.two_pages()))
        assert sorted([r1.status_code, r2.status_code]) == [200, 202]
        assert r1.json()["job"]["id"] == r2.json()["job"]["id"]


def _multipart(boundary: str, head: bytes) -> bytes:
    return (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + head


@pytest.mark.parametrize(
    ("data", "status", "code"),
    [
        (b"", 400, "empty_file"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, 415, "not_a_pdf"),
        (pdfs.encrypted(), 422, "pdf_encrypted"),
        (many_pages(41), 422, "too_many_pages"),
        (pdfs.garbage(), 422, "pdf_unreadable"),
    ],
    ids=["empty", "png", "encrypted", "41-pages", "truncated"],
)
async def test_bad_uploads_are_refused(
    api: ApiFactory, data: bytes, status: int, code: str
) -> None:  # T-API-4
    async with api() as a:
        r = await a.upload(data)
        assert r.status_code == status, r.text
        assert r.json()["error"] == code
        assert r.json()["message"]


async def test_oversized_upload_is_cut_off_early(api: ApiFactory) -> None:  # T-API-4, 16 MB
    boundary = "inkthreadboundary"
    chunk = 1024 * 1024
    total_chunks = 16
    sent = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal sent
        yield _multipart(boundary, b"%PDF-1.7\n")
        for _ in range(total_chunks):
            sent += 1
            yield b"0" * chunk
        yield f"\r\n--{boundary}--\r\n".encode()

    async with api() as a:
        r = await a.client.post(
            "/documents",
            content=body(),
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        assert r.status_code == 413
        assert r.json()["error"] == "file_too_large"
        assert sent <= 16  # cut off just past 15 MB, never read to the end


async def test_declared_length_over_the_limit_is_refused(api: ApiFactory) -> None:
    async with api() as a:
        r = await a.client.post(
            "/documents",
            content=b"x" * 10,
            headers={
                "content-type": "multipart/form-data; boundary=b",
                "content-length": str(64 * 1024 * 1024),
            },
        )
        assert r.status_code == 413


async def test_missing_file_field_is_a_validation_error(api: ApiFactory) -> None:
    async with api() as a:
        r = await a.client.post("/documents", data={"other": "x"})
        assert r.status_code == 422
        assert r.json()["error"] == "validation_error"


async def test_sixth_upload_from_one_ip_is_rate_limited(
    api: ApiFactory, make_settings: Callable[..., Settings]
) -> None:  # T-API-5
    settings = make_settings(uploads_per_hour=5)
    async with api(settings=settings) as a:
        for _ in range(5):
            assert (await a.upload(pdfs.sectioned(), ip="10.0.0.1")).status_code in {200, 202}
        r = await a.upload(pdfs.sectioned(), ip="10.0.0.1")
        assert r.status_code == 429
        assert r.json()["error"] == "rate_limited"
        assert int(r.headers["retry-after"]) > 0
        assert (await a.upload(pdfs.sectioned(), ip="10.0.0.2")).status_code == 200


async def test_full_queue_refuses_new_work(
    api: ApiFactory, sessions: async_sessionmaker[AsyncSession]
) -> None:  # T-API-6
    async with api() as a:
        async with sessions() as s, s.begin():
            for i in range(10):
                doc = await documents.create(
                    s,
                    sha256=f"{i:064x}",
                    file_name=None,
                    page_count=1,
                    byte_size=10,
                    kind="upload",
                    expires_at=None,
                )
                await jobs.create(s, doc.id)
        r = await a.upload(pdfs.sectioned())
        assert r.status_code == 503
        assert r.json()["error"] == "queue_full"
