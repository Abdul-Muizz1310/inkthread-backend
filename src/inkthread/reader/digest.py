"""Build the `ReadingDigest` (spec 11 § 1) from inkgrid's `Document` and `VerificationReport`."""

from __future__ import annotations

import inkgrid

from inkthread.domain.digest import (
    DefectNote,
    FindingNote,
    ReadingDigest,
    TableDigest,
    VerificationSummary,
)


def _table(table: inkgrid.Table) -> TableDigest:
    (region,) = table.regions  # inkgrid guarantees one region per table
    box = region.bbox
    return TableDigest(
        id=table.id,
        page=region.page,
        bbox=(box.x0, box.y0, box.x1, box.y1),
        header_rows=table.grid.header_rows,
        rows=tuple(tuple(cell.text for cell in row) for row in table.to_rows()),
        markdown=table.to_markdown(),
    )


def _verification(report: inkgrid.VerificationReport) -> VerificationSummary:
    v = report.verifier
    return VerificationSummary(
        ok=report.ok,
        engine=f"pdfium {v.pdfium} (pypdfium2 {v.pypdfium2})",
        checked=sum(1 for page in report.pages if page.status == "verified"),
        disagreements=len(report.defects),
        defects=tuple(
            DefectNote(code=str(d.code), page=d.page, message=d.detail) for d in report.defects
        ),
    )


def digest(document: inkgrid.Document, report: inkgrid.VerificationReport) -> ReadingDigest:
    """The tables, verification summary and findings of one reading."""
    return ReadingDigest(
        inkgrid_version=document.producer.inkgrid,
        verification=_verification(report),
        tables=tuple(_table(b) for b in document.blocks if isinstance(b, inkgrid.Table)),
        findings=tuple(
            FindingNote(code=str(f.code), severity=str(f.severity), page=f.page)
            for f in document.findings
        ),
    )
