"""Spec 02 §§ 3-4: title and heading merge (T-ST-10..13)."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.draft import GraphDraft
from inkthread.domain.model import Actor, FlagCode, NodeKind
from inkthread.domain.reading import Reading
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.types import StructureResult


def run(reading: Reading) -> tuple[GraphDraft, StructureResult]:
    draft = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0")
    return draft, build_structure(reading, draft)


def sections(draft: GraphDraft) -> list[str]:
    return [n.text for n in draft.nodes_of(NodeKind.SECTION)]


def test_largest_heading_on_page_one_is_the_title() -> None:  # T-ST-10
    b = ReadingBuilder(pages=2)
    t = b.heading("Fee Schedule", level=1)
    b.heading("1 Scope", level=2, number="1")
    b.para("Applies to members.")
    r = b.heading("Fee Schedule", level=1, page=2)
    b.para("More text.", page=2)
    draft, res = run(b.build())
    doc = draft.nodes_of(NodeKind.DOCUMENT)[0]
    assert doc.text == "Fee Schedule"
    assert doc.label == "Fee Schedule"
    assert doc.source_blocks == [t, r]
    assert doc.made_by.id == "R-SEC-title"
    assert [(r.page, r.bbox) for r in doc.regions] == [(1, b.blocks[0].regions[0].bbox)]
    assert res.title_node == doc.id
    assert sections(draft) == ["1 Scope"]
    assert res.block_to_node[t] == res.block_to_node[r] == doc.id


def test_no_heading_on_page_one_gives_no_title() -> None:  # T-ST-11
    b = ReadingBuilder(pages=2)
    b.para("Preamble.")
    b.heading("Smaller", level=2)
    b.heading("Big", level=1, page=2)
    draft, res = run(b.build())
    doc = draft.nodes_of(NodeKind.DOCUMENT)[0]
    assert doc.text == ""
    assert doc.label == "doc.pdf"
    assert doc.regions == []
    assert res.title_node is None
    assert sections(draft) == ["Smaller", "Big"]


def test_untitled_unnamed_document_is_labelled_document() -> None:
    b = ReadingBuilder(file_name=None)
    b.para("Only text.")
    draft, _ = run(b.build())
    assert draft.nodes_of(NodeKind.DOCUMENT)[0].label == "document"


def test_two_adjacent_same_level_headings_merge() -> None:  # T-ST-12
    b = ReadingBuilder()
    b.heading("Title", level=1)
    h1 = b.heading("Schedule of Fees", level=2, gap=4.0)
    h2 = b.heading("for Members", level=2)
    b.para("Body.")
    draft, res = run(b.build())
    merged = draft.nodes_of(NodeKind.SECTION)
    assert [s.text for s in merged] == ["Schedule of Fees\nfor Members"]
    node = merged[0]
    assert node.source_blocks == [h1, h2]
    assert [f.code for f in node.flags] == [FlagCode.MERGED_HEADING]
    assert node.made_by.id == "R-SEC-merge"
    assert node.made_by.actor is Actor.RULE
    assert res.block_to_node[h1] == res.block_to_node[h2] == node.id


def test_three_headings_merge_in_a_chain() -> None:
    b = ReadingBuilder()
    b.heading("Title", level=1)
    b.heading("A", level=2, gap=2.0)
    b.heading("B", level=2, gap=2.0)
    b.heading("C", level=2)
    draft, _ = run(b.build())
    assert sections(draft) == ["A\nB\nC"]


def test_non_merging_pairs() -> None:  # T-ST-13
    numbered = ReadingBuilder()
    numbered.heading("Title", level=1)
    numbered.heading("Fees", level=2)
    numbered.heading("2 More", level=2, number="2")
    assert sections(run(numbered.build())[0]) == ["Fees", "2 More"]

    keyword = ReadingBuilder()
    keyword.heading("Title", level=1)
    keyword.heading("Fees", level=2)
    keyword.heading("Article IV", level=2)
    assert sections(run(keyword.build())[0]) == ["Fees", "Article IV"]

    levels = ReadingBuilder()
    levels.heading("Title", level=1)
    levels.heading("Fees", level=2)
    levels.heading("Detail", level=3)
    assert sections(run(levels.build())[0]) == ["Fees", "Detail"]

    pages = ReadingBuilder(pages=2)
    pages.heading("Title", level=1)
    pages.heading("Fees", level=2)
    pages.heading("Detail", level=2, page=2)
    assert sections(run(pages.build())[0]) == ["Fees", "Detail"]

    wide = ReadingBuilder()
    wide.heading("Title", level=1)
    wide.heading("Fees", level=2, gap=20.0)
    wide.heading("Detail", level=2)
    assert sections(run(wide.build())[0]) == ["Fees", "Detail"]

    long = ReadingBuilder()
    long.heading("Title", level=1)
    long.heading("x" * 150, level=2, gap=2.0)
    long.heading("y" * 60, level=2)
    assert len(sections(run(long.build())[0])) == 2


def test_merge_respects_the_region_height() -> None:
    b = ReadingBuilder()
    b.heading("Title", level=1)
    b.heading("Tall", level=2, height=30.0, gap=20.0)  # gap 20 <= 0.8 * 30
    b.heading("Next", level=2)
    assert sections(run(b.build())[0]) == ["Tall\nNext"]
