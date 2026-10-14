"""Spec 02 § 10 T-ST-1…4: the adapter on real inkgrid output from synthetic PDFs."""

from __future__ import annotations

import inkgrid
import pdfs
import pytest

from inkthread.domain.reading import RBlock, Reading
from inkthread.reader.adapt import adapt

pytestmark = pytest.mark.integration


def read(data: bytes, *, verify: bool = True) -> Reading:
    doc = inkgrid.read(data)
    return adapt(doc, inkgrid.verify(doc, data) if verify else None)


def only(reading: Reading, kind: str) -> list[RBlock]:
    return [b for b in reading.blocks if b.kind == kind]


def sliced(block: RBlock) -> list[str | None]:
    return [
        None if w.start is None or w.end is None else block.text[w.start : w.end]
        for w in block.words
    ]


def test_t_st_1_paragraph_words_align() -> None:
    reading = read(pdfs.sectioned())
    paragraphs = only(reading, "paragraph")
    assert len(paragraphs) == 3
    for block in paragraphs[1:]:
        assert block.words
        assert sliced(block) == [w.text for w in block.words]


def test_t_st_2_hyphen_join_aligns_without_hyphen() -> None:
    reading = read(pdfs.sectioned())
    para = only(reading, "paragraph")[0]
    left = next(w for w in para.words if w.text == pdfs.HYPHEN_LEFT)
    right = next(w for w in para.words if w.text == pdfs.HYPHEN_RIGHT)
    assert left.start is not None
    assert left.end is not None
    assert para.text[left.start : left.end] == pdfs.HYPHEN_LEFT.removesuffix("-")
    assert right.start == left.end
    assert "settlement" in para.text


def test_t_st_3_table_words_align_inside_table_text() -> None:
    reading = read(pdfs.ruled_table())
    [table] = only(reading, "table")
    assert table.text == "Service Fee\nFiling 350.00\nRenewal 125.50"
    assert len(table.words) == 6
    assert sliced(table) == [w.text for w in table.words]


def test_t_st_4_hidden_words_are_flagged() -> None:
    reading = read(pdfs.hidden_text())
    [para] = only(reading, "paragraph")
    assert {w.text for w in para.words if w.hidden} == set(pdfs.HIDDEN_WORDS)
    assert not any(w.hidden for w in para.words if w.text not in pdfs.HIDDEN_WORDS)
    assert "hidden_text" in {f.code for f in reading.findings}


def test_table_cells_have_page_bboxes() -> None:
    reading = read(pdfs.ruled_table())
    [table] = only(reading, "table")
    grid = table.grid
    assert grid is not None
    assert (grid.n_rows, grid.n_cols, grid.header_rows, grid.source) == (3, 2, 1, "lattice")
    by_text = {c.text: c for c in grid.cells}
    for text, (x0, y0, x1, y1) in pdfs.RULED_CELLS.items():
        cell = by_text[text]
        assert cell.page == 1
        assert cell.bbox is not None
        assert cell.bbox == pytest.approx((x0, y0, x1, y1), abs=2.0)


def test_headings_carry_level_and_number_and_document_facts() -> None:
    data = pdfs.sectioned()
    reading = read(data)
    heads = only(reading, "heading")
    assert [(h.text, h.level, h.number) for h in heads] == [
        (pdfs.SECTIONED_TITLE, 1, None),
        ("1 Scope", 2, "1"),
        ("1.1 Members", 3, "1.1"),
        ("2 Fees", 2, "2"),
    ]
    assert [b.id for b in reading.blocks] == [f"b{i}" for i in range(1, 8)]
    assert all(b.key for b in reading.blocks)
    assert reading.pages[0].number == 1
    assert (reading.pages[0].width, reading.pages[0].height) == (612, 792)
    assert reading.producer["inkgrid"] == inkgrid.__version__
    assert reading.verified
    assert not reading.defects
    assert not read(data, verify=False).verified


def test_footnote_call_becomes_a_link() -> None:
    reading = read(pdfs.footnoted())
    [note] = only(reading, "footnote")
    assert note.label == "1"
    [link] = reading.links
    caller = reading.block(link.from_block)
    assert (link.kind, link.to_block, link.label, link.method, link.status) == (
        "footnote_call",
        note.id,
        "1",
        "superscript",
        "resolved",
    )
    assert link.from_cell is None
    assert caller.markers == ("1",)
    assert [w.text for w in caller.words if w.superscript] == ["1"]


def test_two_pages_regions() -> None:
    reading = read(pdfs.two_pages())
    assert len(reading.pages) == 2
    assert [b.page for b in reading.blocks] == [1, 1, 2, 2]
