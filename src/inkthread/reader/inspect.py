"""Cheap upload checks with pypdfium2: page count and encryption (spec 07 § 4)."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

# pypdfium2 is not thread-safe: every call into PDFium goes through this lock.
_PDFIUM = threading.Lock()


class PdfUnreadable(ValueError):  # noqa: N818  # name fixed by spec 07 § 4
    """The bytes are not a PDF that PDFium can open."""


class PdfEncrypted(ValueError):  # noqa: N818  # name fixed by spec 07 § 4
    """The PDF needs a user password to open."""


@dataclass(frozen=True, slots=True)
class PdfFacts:
    """What an upload check needs to know about a PDF."""

    pages: int
    encrypted: bool


def inspect_pdf(data: bytes) -> PdfFacts:
    """The page count, and whether a security handler is present (an owner password only).

    Raises:
        PdfEncrypted: a user password is required.
        PdfUnreadable: PDFium cannot open the bytes, or they hold no page.
    """
    with _PDFIUM:
        try:
            doc = pdfium.PdfDocument(data)  # type: ignore[no-untyped-call]  # pypdfium2's helpers are unannotated
        except pdfium.PdfiumError as exc:
            password: int = pdfium_c.FPDF_ERR_PASSWORD  # type: ignore[attr-defined]  # pypdfium2.raw is generated ctypes
            if getattr(exc, "err_code", None) == password:
                raise PdfEncrypted(str(exc)) from None
            raise PdfUnreadable(str(exc)) from None
        try:
            pages = len(doc)
            revision: int = pdfium_c.FPDF_GetSecurityHandlerRevision(doc.raw)  # type: ignore[attr-defined]  # pypdfium2.raw is generated ctypes
            encrypted = revision != -1
        finally:
            doc.close()  # type: ignore[no-untyped-call]  # pypdfium2's helpers are unannotated
    if pages < 1:
        msg = "the PDF has no pages"
        raise PdfUnreadable(msg)
    return PdfFacts(pages=pages, encrypted=encrypted)
