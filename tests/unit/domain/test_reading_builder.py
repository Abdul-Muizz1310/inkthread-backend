"""The literal Reading builder lays out valid readings."""

from __future__ import annotations

from readings import ReadingBuilder


def test_builder_aligns_words_and_numbers_blocks() -> None:
    b = ReadingBuilder()
    h = b.heading("1 Fees", number="1")
    p = b.para("Members must pay.")
    t = b.table([["Fee", "Amount"], ["Filing", "$350.00"]])
    r = b.build()
    assert [x.id for x in r.blocks] == [h, p, t] == ["b1", "b2", "b3"]
    para = r.block(p)
    assert all(para.text[w.start : w.end] == w.text for w in para.words if w.start is not None)
    grid = r.block(t).grid
    assert grid is not None
    assert (grid.n_rows, grid.n_cols) == (2, 2)
