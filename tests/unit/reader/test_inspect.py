"""Spec 07 § 4: upload checks read the page count and encryption with pypdfium2."""

from __future__ import annotations

import pdfs
import pytest

from inkthread.reader.inspect import PdfEncrypted, PdfFacts, PdfUnreadable, inspect_pdf


def test_counts_pages() -> None:
    assert inspect_pdf(pdfs.two_pages()) == PdfFacts(pages=2, encrypted=False)


def test_user_password_raises_encrypted() -> None:
    with pytest.raises(PdfEncrypted):
        inspect_pdf(pdfs.encrypted())


def test_owner_only_encryption_opens_and_reports_encrypted() -> None:
    assert inspect_pdf(pdfs.encrypted(user_pw="")) == PdfFacts(pages=1, encrypted=True)


@pytest.mark.parametrize("data", [pdfs.garbage(), b"", b"hello"])
def test_garbage_raises_unreadable(data: bytes) -> None:
    with pytest.raises(PdfUnreadable):
        inspect_pdf(data)
