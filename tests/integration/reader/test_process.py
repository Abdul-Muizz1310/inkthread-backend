"""Spec 08 § 6 T-PJ-8…11: the reader runs in a real spawned child process."""

from __future__ import annotations

import pdfs
import pytest

from inkthread.reader.process import ReadFailure, ReadSuccess, read_in_child

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n"


async def test_t_pj_8_two_pages_come_back_with_two_pngs() -> None:
    outcome = await read_in_child(pdfs.two_pages(), timeout_s=60)
    assert isinstance(outcome, ReadSuccess)
    assert len(outcome.reading.pages) == 2
    assert outcome.reading.verified
    assert len(outcome.pngs) == 2
    assert all(p.startswith(PNG) for p in outcome.pngs)
    # 2x render: a 612-point-wide page is 1224 pixels wide (PNG IHDR width, big-endian).
    assert int.from_bytes(outcome.pngs[0][16:20], "big") == 1224


@pytest.mark.parametrize(
    ("data", "code"),
    [(pdfs.encrypted(), "pdf_encrypted"), (pdfs.garbage(), "pdf_unreadable")],
    ids=["encrypted", "garbage"],
)
async def test_t_pj_9_bad_pdfs_fail_with_codes(data: bytes, code: str) -> None:
    outcome = await read_in_child(data, timeout_s=60)
    assert isinstance(outcome, ReadFailure)
    assert outcome.code == code
    assert outcome.message


async def test_t_pj_10_timeout_terminates_the_child() -> None:
    outcome = await read_in_child(pdfs.ruled_table(), timeout_s=0.05)
    assert isinstance(outcome, ReadFailure)
    assert outcome.code == "read_timeout"


async def test_t_pj_11_image_only_pdf_has_no_text_layer() -> None:
    outcome = await read_in_child(pdfs.image_only(), timeout_s=60)
    assert isinstance(outcome, ReadFailure)
    assert outcome.code == "no_text_layer"


async def test_memory_limit_failure_is_a_code_not_a_crash() -> None:
    outcome = await read_in_child(pdfs.sectioned(), timeout_s=60, memory_limit_mb=64)
    assert isinstance(outcome, ReadFailure)
    assert outcome.code == "reader_failed"
