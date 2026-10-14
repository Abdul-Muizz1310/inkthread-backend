"""Spec 02 § 9: per-page word geometry."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.draft import GraphDraft
from inkthread.domain.reading import RWord
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.types import GeomWord


def test_words_map_to_node_offsets_and_merged_headings_shift() -> None:
    b = ReadingBuilder(pages=2)
    b.heading("Doc", level=1, gap=20.0)
    f = b.furniture("Page 1")
    b.heading("Fees", level=2, gap=2.0)
    b.heading("for All", level=2, gap=20.0)
    unaligned = RWord(start=None, end=None, page=2, bbox=(1.0, 1.0, 2.0, 2.0), text="zz")
    b.para("Body", page=2, words=(unaligned,))
    reading = b.build()
    draft = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0")
    res = build_structure(reading, draft)
    section = res.block_to_node["b3"]
    doc = res.block_to_node["b1"]
    by_text = {
        draft.node(w.node).text[w.start : w.end] if w.node and w.start is not None else None: w
        for w in res.geometry[1]
    }
    assert by_text["All"].node == section
    assert (by_text["All"].start, by_text["All"].end) == (9, 12)
    assert by_text["Doc"].node == doc
    assert f not in res.block_to_node
    furniture = [w for w in res.geometry[1] if w.node is None]
    assert [(w.start, w.end) for w in furniture] == [(0, 4), (5, 6)]
    assert res.geometry[2] == []
    assert isinstance(by_text["Fees"], GeomWord)
