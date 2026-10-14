"""What the spawned reader child runs (spec 08 § 3): inkgrid's read and verify, and page PNGs.

Errors come back as codes, never exceptions, so the parent only ever parses a dict.
"""

from __future__ import annotations

import sys
from multiprocessing.connection import Connection

import inkgrid
import pymupdf


def _limit_memory(limit_mb: int) -> None:
    """Cap the child's address space (Linux only; a no-op elsewhere or when 0)."""
    if limit_mb <= 0 or not sys.platform.startswith("linux"):
        return
    import resource  # noqa: PLC0415  # POSIX-only module

    cap = limit_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (cap, cap))


def _render(pdf: bytes, scale: float) -> list[bytes]:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # type: ignore[no-untyped-call]  # PyMuPDF is unannotated here
        # PDF space is 72 dpi, so a scale of 2 renders at 144 dpi.
        dpi = round(72 * scale)
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]


def read_document(pdf: bytes, render_scale: float = 2.0) -> dict[str, object]:
    """`{document_json, report_json, pngs}`, or `{error, message}` with a failure code."""
    try:
        doc = inkgrid.read(pdf)
        report = inkgrid.verify(doc, pdf)
        pngs = _render(pdf, render_scale)
    except (inkgrid.PasswordRequired, inkgrid.WrongPassword) as exc:
        return {"error": "pdf_encrypted", "message": str(exc)}
    except inkgrid.PdfOpenError as exc:
        return {"error": "pdf_unreadable", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001  # the child reports every failure as a code
        return {"error": "reader_failed", "message": f"{type(exc).__name__}: {exc}"}
    return {
        "document_json": doc.model_dump_json(by_alias=True),
        "report_json": report.model_dump_json(by_alias=True),
        "pngs": pngs,
    }


def run_child(conn: Connection, pdf: bytes, memory_limit_mb: int, render_scale: float) -> None:
    """The spawned process's target: read, then send the result dict through the pipe."""
    try:
        _limit_memory(memory_limit_mb)
        result = read_document(pdf, render_scale)
    except MemoryError:
        result = {"error": "reader_failed", "message": "MemoryError: the memory limit was hit"}
    try:
        conn.send(result)
    finally:
        conn.close()
