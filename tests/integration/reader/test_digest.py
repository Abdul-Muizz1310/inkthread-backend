"""Spec 11 cases T-RD-1…4: the reading digest from real inkgrid output on synthetic PDFs."""

from __future__ import annotations

import importlib.metadata
import json

import inkgrid
import pdfs
import pytest

from inkthread.domain.digest import ReadingDigest
from inkthread.reader.digest import digest

pytestmark = pytest.mark.integration


def read(data: bytes) -> tuple[inkgrid.Document, inkgrid.VerificationReport]:
    doc = inkgrid.read(data)
    return doc, inkgrid.verify(doc, data)


def test_T_RD_1_a_ruled_table_is_kept_with_rows_and_markdown() -> None:
    doc, report = read(pdfs.ruled_table())
    d = digest(doc, report)
    tables = [b for b in doc.blocks if isinstance(b, inkgrid.Table)]
    assert len(tables) == 1
    (src,) = tables
    (t,) = d.tables
    assert t.id == src.id
    assert t.page == 1 == src.regions[0].page
    box = src.regions[0].bbox
    assert t.bbox == (box.x0, box.y0, box.x1, box.y1)
    assert t.header_rows == src.grid.header_rows >= 1
    assert t.rows == tuple(tuple(c.text for c in row) for row in src.to_rows())
    assert len({len(r) for r in t.rows}) == 1
    assert t.markdown == src.to_markdown()
    assert "|" in t.markdown


def test_T_RD_2_no_table_and_a_clean_report() -> None:
    doc, report = read(pdfs.sectioned())
    d = digest(doc, report)
    assert d.tables == ()
    assert report.ok
    assert d.verification.ok is True
    assert d.verification.disagreements == 0
    assert d.verification.defects == ()
    verified = sum(1 for p in report.pages if p.status == "verified")
    assert d.verification.checked == verified == len(doc.pages)


def test_T_RD_3_defects_are_summarised_and_advisories_are_not() -> None:
    doc, report = read(pdfs.ruled_table())
    table = next(b for b in doc.blocks if isinstance(b, inkgrid.Table))
    data = report.model_dump(mode="json", by_alias=True)
    data["defects"] = [
        {"code": "doubled", "page": 1, "text": "ab", "detail": "2 characters are read twice"},
        {"code": "invented", "page": 1, "text": "z", "detail": "1 character is not on the page"},
    ]
    data["advisories"] = [
        {
            "code": "order",
            "page": 1,
            "block": table.id,
            "cell": [0, 0],
            "detail": "read out of order",
        }
    ]
    flawed = inkgrid.VerificationReport.model_validate_json(json.dumps(data))
    d = digest(doc, flawed)
    assert d.verification.ok is False
    assert d.verification.disagreements == 2
    assert [(x.code, x.page, x.message) for x in d.verification.defects] == [
        ("doubled", 1, "2 characters are read twice"),
        ("invented", 1, "1 character is not on the page"),
    ]


def test_T_RD_4_versions_are_named() -> None:
    doc, report = read(pdfs.sectioned())
    d = digest(doc, report)
    assert d.inkgrid_version == doc.producer.inkgrid == importlib.metadata.version("inkgrid")
    v = report.verifier
    assert d.verification.engine == f"pdfium {v.pdfium} (pypdfium2 {v.pypdfium2})"


def test_findings_keep_code_severity_and_page() -> None:
    doc, report = read(pdfs.hidden_text())
    d = digest(doc, report)
    assert [(f.code, f.severity, f.page) for f in d.findings] == [
        (str(f.code), str(f.severity), f.page) for f in doc.findings
    ]
    assert d.findings, "the hidden-text fixture carries a finding"


def test_the_digest_round_trips_as_json() -> None:
    doc, report = read(pdfs.ruled_table())
    d = digest(doc, report)
    assert ReadingDigest.model_validate_json(d.model_dump_json()) == d


async def test_the_child_reader_returns_the_digest() -> None:
    from inkthread.reader.process import ReadSuccess, read_in_child

    outcome = await read_in_child(pdfs.ruled_table(), timeout_s=60)
    assert isinstance(outcome, ReadSuccess)
    assert len(outcome.digest.tables) == 1
    assert outcome.digest.verification.checked == 1
