"""Spec 02 § 5: the section tree (T-ST-14..20) and a document with no headings."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.draft import GraphDraft
from inkthread.domain.model import EdgeType, NodeKind
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.types import StructureResult

DOC = "<doc>"


def run(b: ReadingBuilder) -> tuple[GraphDraft, StructureResult]:
    reading = b.build()
    draft = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0")
    return draft, build_structure(reading, draft)


def parent_texts(b: ReadingBuilder) -> dict[str, str]:
    """Each node's text -> its parent's text (`<doc>` for the document)."""
    draft, _ = run(b)
    out: dict[str, str] = {}
    for n in draft.nodes.values():
        if n.section is None:
            continue
        parent = draft.node(n.section)
        out[n.text] = DOC if parent.kind is NodeKind.DOCUMENT else parent.text
    return out


def builder() -> ReadingBuilder:
    """A builder whose first block is a level-1 title, so the headings under test open sections."""
    b = ReadingBuilder()
    b.heading("Doc", level=1, gap=20.0)
    return b


def heading(b: ReadingBuilder, text: str, *, level: int = 2, number: str | None = None) -> None:
    b.heading(text, level=level, number=number, gap=20.0)


def test_numbers_nest_by_prefix() -> None:  # T-ST-14
    b = builder()
    for n in ("1", "1.1", "1.2", "2", "2.1"):
        heading(b, f"{n} Head", number=n)
    assert parent_texts(b) == {
        "1 Head": DOC,
        "1.1 Head": "1 Head",
        "1.2 Head": "1 Head",
        "2 Head": DOC,
        "2.1 Head": "2 Head",
    }


def test_orphan_subnumber_goes_to_the_document() -> None:  # T-ST-15
    b = builder()
    for n in ("1", "1.2", "2.1"):
        heading(b, f"{n} Head", number=n)
    assert parent_texts(b)["2.1 Head"] == DOC


def test_numbered_sections_nest_under_parts() -> None:  # T-ST-16
    b = builder()
    heading(b, "Part 1 General")
    heading(b, "1 Scope", number="1")
    heading(b, "2 Fees", number="2")
    heading(b, "Part 2 Special")
    heading(b, "3 Other", number="3")
    assert parent_texts(b) == {
        "Part 1 General": DOC,
        "1 Scope": "Part 1 General",
        "2 Fees": "Part 1 General",
        "Part 2 Special": DOC,
        "3 Other": "Part 2 Special",
    }


def test_appendix_closes_back_to_the_document() -> None:  # T-ST-17
    b = builder()
    heading(b, "3 Fees", number="3")
    heading(b, "3.2 Late", number="3.2")
    heading(b, "Appendix A Forms")
    b.para("Form text.")
    got = parent_texts(b)
    assert got["Appendix A Forms"] == DOC
    assert got["Form text."] == "Appendix A Forms"


def test_plain_heading_under_numbered_by_size() -> None:  # T-ST-18
    b = builder()
    heading(b, "1 Fees", number="1", level=2)
    heading(b, "Notes on fees", level=3)
    heading(b, "General", level=2)
    heading(b, "2 More", number="2", level=2)
    heading(b, "Bigger", level=1)
    got = parent_texts(b)
    assert got["Notes on fees"] == "1 Fees"
    assert got["General"] == DOC
    assert got["Bigger"] == DOC


def test_equal_plain_headings_nest_until_content() -> None:  # T-ST-19
    b = builder()
    heading(b, "Banner")
    heading(b, "First")
    b.para("First body.")
    heading(b, "Second")
    got = parent_texts(b)
    assert got["Banner"] == DOC
    assert got["First"] == "Banner"
    assert got["First body."] == "First"
    assert got["Second"] == "Banner"


def test_content_before_any_heading_is_under_the_document() -> None:  # T-ST-20
    b = builder()
    b.para("Preamble.")
    heading(b, "1 Fees", number="1")
    b.para("Body.")
    got = parent_texts(b)
    assert got["Preamble."] == DOC
    assert got["Body."] == "1 Fees"


def test_no_headings_document() -> None:  # plan review focus 1
    b = ReadingBuilder(pages=2)
    b.para("One.")
    b.item("Two.", label="(a)")
    b.para("Three.", page=2)
    draft, res = run(b)
    doc = draft.nodes_of(NodeKind.DOCUMENT)[0]
    assert res.title_node is None
    assert doc.text == ""
    assert not draft.nodes_of(NodeKind.SECTION)
    parts = [n for n in draft.nodes.values() if n.kind is not NodeKind.DOCUMENT]
    assert len(parts) == 3
    assert all(p.section == doc.id and p.depth == 1 for p in parts)
    contains = [e for e in draft.edges.values() if e.type is EdgeType.CONTAINS]
    assert sorted(e.target for e in contains) == sorted(p.id for p in parts)


def test_depth_and_order_follow_the_tree() -> None:
    b = builder()
    heading(b, "1 A", number="1")
    heading(b, "1.1 B", number="1.1")
    b.para("Body.")
    draft, _ = run(b)
    by_text = {n.text: n for n in draft.nodes.values()}
    assert [by_text[t].depth for t in ("1 A", "1.1 B", "Body.")] == [1, 2, 3]
    assert [by_text[t].order for t in ("1 A", "1.1 B", "Body.")] == [2, 3, 4]


def test_section_index_keys() -> None:
    b = builder()
    heading(b, "Part II General")
    heading(b, "1 Scope", number="1")
    heading(b, "1.2 Late", number="1.2")
    heading(b, "Schedule B Forms")
    heading(b, "§ 7 Rules")
    heading(b, "A. Lettered", number="A.")
    draft, res = run(b)
    ids = {n.text: n.id for n in draft.nodes_of(NodeKind.SECTION)}
    idx = res.sections
    assert idx.find("part", "II") == ids["Part II General"]
    assert idx.find("num", "1.2") == ids["1.2 Late"]
    assert idx.find("appendix", "B") == ids["Schedule B Forms"]
    assert idx.find("section", "7") == ids["§ 7 Rules"]
    assert idx.find("num", "A") == ids["A. Lettered"]
    assert idx.find("article", "1") == ids["1 Scope"]  # falls back to the bare number
    assert idx.numbers[ids["1.2 Late"]] == "1.2"


def test_section_ids_use_ancestor_titles_and_twins() -> None:
    b = builder()
    heading(b, "1 A", number="1")
    b.para("Same.")
    b.para("Same.")
    draft, _ = run(b)
    paras = draft.nodes_of(NodeKind.PARAGRAPH)
    assert paras[1].id == paras[0].id + ":2"
