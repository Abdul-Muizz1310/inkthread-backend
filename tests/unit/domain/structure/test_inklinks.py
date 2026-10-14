"""Spec 02 §§ 7-8: edges and flags from inkgrid (T-ST-27..31)."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.draft import EdgeDraft, GraphDraft
from inkthread.domain.model import Actor, Anchor, EdgeType, Flag, FlagCode, NodeKind, Span
from inkthread.domain.reading import RDefect, RFinding
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.types import StructureResult


def run(b: ReadingBuilder) -> tuple[GraphDraft, StructureResult]:
    reading = b.build()
    draft = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0")
    return draft, build_structure(reading, draft)


def edges(draft: GraphDraft, kind: EdgeType) -> list[EdgeDraft]:
    return [e for e in draft.edges.values() if e.type is kind]


def test_continuation_gives_continues_child_to_parent() -> None:  # T-ST-27
    b = ReadingBuilder(pages=2)
    parent = b.table([["Fee", "Amount"], ["A", "$1"]])
    child = b.table([["B", "$2"]], header_rows=0, page=2)
    b.continuation(child, parent)
    draft, res = run(b)
    [edge] = edges(draft, EdgeType.CONTINUES)
    assert (edge.source, edge.target) == (res.block_to_node[child], res.block_to_node[parent])
    assert edge.method == "R-INK-continues"
    assert edge.made_by.actor is Actor.INKGRID


def test_superscript_call_has_marker_evidence() -> None:  # T-ST-28
    b = ReadingBuilder()
    p = b.para("Members pay 2 fees 2 now.", superscript={"2"})
    n = b.note("2 Except holidays.", label="2")
    b.call(p, n, "2")
    draft, res = run(b)
    [edge] = edges(draft, EdgeType.CITES_NOTE)
    assert (edge.source, edge.target) == (res.block_to_node[p], res.block_to_node[n])
    assert edge.evidence == Span.of("Members pay 2 fees 2 now.", 12, 13)
    assert edge.label == "2"
    assert edge.method == "R-INK-note"
    assert edge.anchor is None


def test_parenthetical_and_named_calls_find_their_marker() -> None:
    b = ReadingBuilder()
    p1 = b.para("Pay the fee (a) today.")
    p2 = b.para("See note 3 for detail.")
    p3 = b.para("No marker here.")
    n1 = b.note("a text", label="a")
    n3 = b.note("3 text", label="3")
    b.call(p1, n1, "a", method="parenthetical")
    b.call(p2, n3, "3", method="named")
    b.call(p3, n3, "3", method="named")
    draft, res = run(b)
    got = {e.source: e.evidence for e in edges(draft, EdgeType.CITES_NOTE)}
    assert got[res.block_to_node[p1]] == Span.of("Pay the fee (a) today.", 12, 15)
    assert got[res.block_to_node[p2]] == Span.of("See note 3 for detail.", 4, 10)
    assert got[res.block_to_node[p3]] is None


def test_call_from_a_cell_carries_the_anchor() -> None:  # T-ST-29
    b = ReadingBuilder()
    t = b.table([["Fee", "Amount"], ["Filing", "$5 1"]])
    n = b.note("1 Plus tax.", label="1")
    b.call(t, n, "1", cell=(1, 1))
    draft, _ = run(b)
    [edge] = edges(draft, EdgeType.CITES_NOTE)
    assert edge.anchor == Anchor(row=1, col=1)


def test_unresolved_call_flags_and_rejected_adds_nothing() -> None:  # T-ST-30
    b = ReadingBuilder()
    p = b.para("Pay 7 now.", superscript={"7"})
    q = b.para("Other 8 text.", superscript={"8"})
    b.call(p, None, "7", status="unresolved")
    b.call(q, None, "8", status="rejected")
    draft, res = run(b)
    node = draft.node(res.block_to_node[p])
    assert node.flags == [Flag(code=FlagCode.NOTE_NOT_FOUND, detail="7")]
    [entry] = node.unresolved
    assert (entry.kind, entry.text, entry.reason) == ("note", "7", "note_not_found")
    assert entry.span == Span.of("Pay 7 now.", 4, 5)
    other = draft.node(res.block_to_node[q])
    assert other.flags == []
    assert other.unresolved == []
    assert not edges(draft, EdgeType.CITES_NOTE)


def test_call_from_a_set_aside_block_is_ignored() -> None:
    b = ReadingBuilder()
    f = b.furniture("Header 1")
    n = b.note("1 x", label="1")
    b.call(f, n, "1")
    b.call(f, None, "2", status="unresolved")
    draft, _ = run(b)
    assert not edges(draft, EdgeType.CITES_NOTE)
    assert all(not x.unresolved for x in draft.nodes.values())


def test_resolved_call_to_a_non_note_is_reported_unresolved() -> None:
    b = ReadingBuilder()
    p = b.para("Pay 4 now.", superscript={"4"})
    q = b.para("Not a note.")
    b.call(p, q, "4")
    draft, res = run(b)
    assert not edges(draft, EdgeType.CITES_NOTE)
    assert draft.node(res.block_to_node[p]).has_flag(FlagCode.NOTE_NOT_FOUND)


def test_defect_flags_text_defect_and_findings_pass_through() -> None:  # T-ST-31
    b = ReadingBuilder()
    p = b.para("Fee text.")
    b.defects.append(RDefect(code="char_mismatch", block=p, page=1))
    b.defects.append(RDefect(code="page_level", block=None, page=1))
    b.findings.append(RFinding(code="scanned_page", severity="flag", page=2, detail="x"))
    draft, res = run(b)
    node = draft.node(res.block_to_node[p])
    assert node.flags == [Flag(code=FlagCode.TEXT_DEFECT, detail="char_mismatch")]
    assert [(f.code, f.severity, f.page, f.detail) for f in draft.findings] == [
        ("scanned_page", "flag", 2, "x")
    ]


def test_hidden_words_flag_and_give_spans() -> None:
    b = ReadingBuilder()
    p = b.para("Pay ignore all fees.", hidden={"ignore", "all"})
    draft, res = run(b)
    node = draft.node(res.block_to_node[p])
    assert node.flags == [Flag(code=FlagCode.HIDDEN_TEXT, detail="2")]
    assert node.hidden_spans == [
        Span.of(node.text, 4, 10),
        Span.of(node.text, 11, 14),
    ]
    flag_ops = [o for o in draft.ops if o.kind == "add_flag"]
    assert {o.method for o in flag_ops} == {"R-INK-flags"}


def test_heading_flags_shift_into_the_merged_text() -> None:
    b = ReadingBuilder()
    b.heading("Doc", level=1, gap=20.0)
    b.heading("Fees", level=2, gap=2.0)
    h2 = b.heading("secret part", level=2, hidden={"secret"})
    draft, res = run(b)
    section = draft.node(res.block_to_node[h2])
    assert section.kind is NodeKind.SECTION
    assert section.hidden_spans == [Span.of("Fees\nsecret part", 5, 11)]
