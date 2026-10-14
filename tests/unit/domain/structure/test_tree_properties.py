"""Spec 02 T-ST-21 and T-ST-32 as properties, plus freezing the draft into a contract `Graph`."""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st
from readings import ReadingBuilder

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.model import (
    Confidence,
    DocumentInfo,
    Edge,
    EdgeType,
    Graph,
    GraphStats,
    Node,
    NodeKind,
    NodeSource,
    Provenance,
    Tier,
)
from inkthread.domain.reading import Reading
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.types import StructureResult
from inkthread.domain.text import cut_label

OK = Confidence(tier=Tier.A, score=1.0)


# --- freezing helper (test-only) ---------------------------------------------------------


def freeze_node(n: NodeDraft) -> Node:
    if n.kind is NodeKind.DOCUMENT:
        label, cut = n.label or "document", False
    else:
        label, cut = cut_label(n.text)
    return Node(
        id=n.id,
        kind=n.kind,
        label=label,
        label_truncated=cut,
        text=n.text,
        order=n.order,
        section=n.section,
        depth=n.depth,
        regions=tuple(n.regions),
        table=n.table,
        marker=n.marker,
        flags=tuple(sorted(n.flags, key=lambda f: (f.code.value, f.detail or ""))),
        hidden_spans=tuple(n.hidden_spans),
        unresolved=tuple(n.unresolved),
        confidence=OK,
        source=NodeSource(blocks=tuple(n.source_blocks), keys=tuple(n.source_keys)),
        made_by=n.made_by,
    )


def freeze_edge(e: EdgeDraft) -> Edge:
    return Edge.make(
        type=e.type,
        source=e.source,
        target=e.target,
        basis=e.basis,
        method=e.method,
        made_by=e.made_by,
        confidence=OK,
        evidence=e.evidence,
        evidence_on=e.evidence_on,
        anchor=e.anchor,
        label=e.label,
        flags=tuple(e.flags),
    )


def freeze(reading: Reading, draft: GraphDraft, res: StructureResult) -> Graph:
    order = list(EdgeType)
    doc_title = draft.node(res.title_node).text if res.title_node else None
    return Graph(
        document=DocumentInfo(
            sha256=reading.sha256,
            file_name=reading.file_name,
            title=doc_title,
            title_node=res.title_node,
            page_count=len(reading.pages),
            pages=reading.pages,
        ),
        nodes=tuple(freeze_node(n) for n in sorted(draft.nodes.values(), key=lambda n: n.order)),
        edges=tuple(
            freeze_edge(e)
            for e in sorted(
                draft.edges.values(),
                key=lambda e: (order.index(e.type), e.source, e.target, e.id),
            )
        ),
        set_aside=tuple(draft.set_aside),
        findings=tuple(draft.findings),
        stats=GraphStats(nodes_by_kind={}, edges_by_type={}, roles={}, tiers={}),
        provenance=Provenance(
            pipeline_version="1.0.0",
            inkgrid_version="0.1.0",
            prompts_hash="",
            models={},
            ops_head="",
            ops_count=len(draft.ops),
            graph_hash="",
            rejected=(),
        ),
    )


# --- generated readings ------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    kind: str  # heading | para | item | furniture
    level: int
    number: str | None
    word: str
    gap: float
    next_page: bool


_KEYWORDS = ["", "", "", "Part 1 ", "Article 2 ", "Section 3 ", "Appendix A "]
_NUMBERS = [None, None, "1", "1.1", "1.2", "2", "2.1", "2.1.1", "A."]

steps = st.builds(
    Step,
    kind=st.sampled_from(["heading", "heading", "para", "para", "item", "furniture"]),
    level=st.integers(min_value=1, max_value=4),
    number=st.sampled_from(_NUMBERS),
    word=st.sampled_from(["Fees", "Scope", "Rules", "Fees 3", "Terms", *_KEYWORDS[3:]]),
    gap=st.sampled_from([2.0, 20.0]),
    next_page=st.booleans(),
)


def make_reading(seq: list[Step]) -> Reading:
    pages = 1 + sum(1 for s in seq if s.next_page)
    b = ReadingBuilder(pages=min(pages, 3))
    page = 1
    for s in seq:
        if s.next_page and page < b.pages:
            page += 1
        match s.kind:
            case "heading":
                text = f"{s.number} {s.word}" if s.number else s.word
                b.heading(text, level=s.level, number=s.number, page=page, gap=s.gap)
            case "para":
                b.para(f"{s.word} text.", page=page)
            case "item":
                b.item(s.word, label="(a)", page=page)
            case _:
                b.furniture(f"Header {s.word}", page=page)
    return b.build()


def run(reading: Reading) -> tuple[GraphDraft, StructureResult]:
    draft = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0")
    return draft, build_structure(reading, draft)


@settings(max_examples=300, deadline=None)
@given(st.lists(steps, max_size=25))
def test_tree_and_partition_hold(seq: list[Step]) -> None:  # T-ST-21, T-ST-32
    reading = make_reading(seq)
    draft, res = run(reading)
    nodes = draft.nodes
    doc = draft.nodes_of(NodeKind.DOCUMENT)[0]

    # T-ST-32: every block is cited by exactly one node or exactly one set-aside entry
    cited = [bid for n in nodes.values() for bid in n.source_blocks]
    cited += [e.block for e in draft.set_aside]
    assert sorted(cited) == sorted(b.id for b in reading.blocks)

    # T-ST-21: contains edges form a tree rooted at the document, matching `section`
    incoming: dict[str, list[str]] = {}
    for e in draft.edges.values():
        if e.type is EdgeType.CONTAINS:
            incoming.setdefault(e.target, []).append(e.source)
    for n in nodes.values():
        if n.kind is NodeKind.DOCUMENT:
            assert n.id not in incoming
            continue
        assert incoming[n.id] == [n.section]
        assert n.section is not None
        parent = nodes[n.section]
        assert parent.kind in {NodeKind.SECTION, NodeKind.DOCUMENT}
        assert n.depth == parent.depth + 1  # depth equals tree depth
        assert n.order > parent.order  # a parent precedes its children
        texts = [reading.block(bid).text for bid in n.source_blocks]
        assert n.text == "\n".join(texts)  # X1 verbatim
    # reading order within each parent: the children's orders follow block order
    for parent_id in {n.section for n in nodes.values() if n.section}:
        kids = [n for n in nodes.values() if n.section == parent_id]
        index = {b.id: i for i, b in enumerate(reading.blocks)}
        assert [k.order for k in kids] == sorted(k.order for k in kids)
        assert all(k.order == 1 + index[k.source_blocks[0]] for k in kids)
    assert doc.order == 0
    assert doc.depth == 0

    graph = freeze(reading, draft, res)  # every contract invariant
    assert len(graph.nodes) == len(nodes)


def test_rich_document_freezes_into_a_valid_graph() -> None:
    b = ReadingBuilder(pages=2)
    b.furniture("ACME")
    b.heading("Fee Schedule", level=1, gap=20.0)
    b.heading("Contents", level=2, gap=20.0)
    b.para("Fees ..... 2")
    b.para("Scope ..... 3")
    b.heading("1 Fees", level=2, number="1", gap=20.0)
    p = b.para("Members pay 5 now.", superscript={"5"}, hidden={"now."})
    t = b.table([["Fee", "Amount"], ["Filing", "$5 1"]])
    t2 = b.table([["Late", "$9"]], header_rows=0, page=2)
    b.continuation(t2, t)
    n5 = b.note("5 Unless waived.", label="5", page=2)
    n1 = b.note("1 Plus tax.", label="1", page=2)
    b.call(p, n5, "5")
    b.call(t, n1, "1", cell=(1, 1))
    b.call(p, None, "9", status="unresolved")
    b.heading("Fee Schedule", level=1, page=2)
    reading = b.build()
    draft, res = run(reading)
    graph = freeze(reading, draft, res)
    assert graph.document.title == "Fee Schedule"
    assert {e.type for e in graph.edges} == {
        EdgeType.CONTAINS,
        EdgeType.CONTINUES,
        EdgeType.CITES_NOTE,
    }
    assert [s.reason for s in graph.set_aside] == [
        "R-SET-furniture",
        "R-SET-toc",
        "R-SET-toc",
        "R-SET-toc",
    ]
    # geometry: words of set-aside blocks carry no node; content words carry theirs
    page1 = res.geometry[1]
    assert any(w.node is None for w in page1)
    assert all(w.node in draft.nodes for w in page1 if w.node is not None)
    assert set(res.geometry) == {1, 2}
