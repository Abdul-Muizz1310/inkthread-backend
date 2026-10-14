"""A realistic hand-built draft and its reading, for the finalize, why and export tests.

It does not use the structure stage: every node, edge, role and flag is added by hand, through the
draft's own mutators, so the op log is exactly what a pipeline would record.
"""

from __future__ import annotations

from dataclasses import dataclass

from readings import ReadingBuilder

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft, RoleDraft
from inkthread.domain.model import (
    Actor,
    Basis,
    CellInfo,
    EdgeType,
    Flag,
    FlagCode,
    Maker,
    NodeKind,
    Region,
    Role,
    SetAside,
    Span,
    TableInfo,
    Unresolved,
    Verdict,
)
from inkthread.domain.reading import Reading

TITLE = Maker(actor=Actor.RULE, id="R-SEC-title")
CONTAINS = Maker(actor=Actor.RULE, id="R-SEC-contains")
PART = Maker(actor=Actor.RULE, id="R-SEC-part")
NOTE = Maker(actor=Actor.INKGRID, id="inkgrid")
FURNITURE = Maker(actor=Actor.RULE, id="R-SET-furniture")
CLASSIFY = Maker(actor=Actor.AGENT, id="A-classify", model="m/producer", request_key="rk-classify")
RELATE = Maker(actor=Actor.AGENT, id="A-relate", model="m/producer", request_key="rk-relate")
VERIFY = Maker(actor=Actor.VERIFIER, id="A-verify", model="m/verifier", request_key="rk-verify")

P1 = "Members must pay the Annual Fee.1 See note 2"
P2 = "Annual Fee means the yearly charge unless waived."


@dataclass
class Sample:
    """The reading, the filled draft and the ids a test needs."""

    reading: Reading
    draft: GraphDraft
    doc: str
    section: str
    p1: str
    p2: str
    table: str
    note: str
    term: str
    agent_edge: str


def _regions(reading: Reading, block: str) -> list[Region]:
    return [Region(page=r.page, bbox=r.bbox) for r in reading.block(block).regions]


def sample() -> Sample:
    b = ReadingBuilder()
    b_title = b.heading("Fee Schedule", level=0)
    b_furn = b.furniture("Page 1")
    b_sec = b.heading("1 Fees", level=1, number="1")
    b_p1 = b.para(P1)
    b_p2 = b.para(P2)
    b_tab = b.table([["Fee", "Amount"], ["Annual", "100"]])
    b_note = b.note("Payable in advance.", label="1")
    b.call(b_p1, b_note, "1")
    b.call(b_p1, None, "2", status="unresolved")
    reading = b.build()

    d = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0", file_name="doc.pdf")
    s = "structure"
    furn = reading.block(b_furn)
    d.set_aside_block(
        SetAside(
            block=b_furn,
            kind="furniture",
            text=furn.text,
            page=furn.page,
            bbox=furn.regions[0].bbox,
            reason="repeats",
        ),
        stage=s,
        maker=FURNITURE,
    )
    doc = "d:" + reading.sha256[:16]
    d.add_node(
        NodeDraft(
            id=doc,
            kind=NodeKind.DOCUMENT,
            text="Fee Schedule",
            order=0,
            section=None,
            depth=0,
            regions=[],
            made_by=TITLE,
            source_blocks=[b_title],
        ),
        stage=s,
    )
    sec = "s:fees"
    d.add_node(
        NodeDraft(
            id=sec,
            kind=NodeKind.SECTION,
            text="1 Fees",
            order=1,
            section=doc,
            depth=1,
            regions=_regions(reading, b_sec),
            made_by=CONTAINS,
            source_blocks=[b_sec],
        ),
        stage=s,
    )
    d.add_edge(
        EdgeDraft(
            type=EdgeType.CONTAINS,
            source=doc,
            target=sec,
            basis=Basis.EXPLICIT,
            method="R-SEC-contains",
            made_by=CONTAINS,
        ),
        stage=s,
    )
    parts: list[tuple[str, NodeKind, str, str]] = [
        ("p:one", NodeKind.PARAGRAPH, b_p1, P1),
        ("p:two", NodeKind.PARAGRAPH, b_p2, P2),
        ("p:tab", NodeKind.TABLE, b_tab, reading.block(b_tab).text),
        ("p:note", NodeKind.NOTE, b_note, "Payable in advance."),
    ]
    grid = reading.block(b_tab).grid
    assert grid is not None
    table = TableInfo(
        n_rows=grid.n_rows,
        n_cols=grid.n_cols,
        header_rows=grid.header_rows,
        source=grid.source,
        cells=tuple(
            CellInfo(
                row=c.row,
                col=c.col,
                row_span=c.row_span,
                col_span=c.col_span,
                text=c.text,
                is_header=c.row < grid.header_rows,
                page=c.page,
                bbox=c.bbox,
            )
            for c in grid.cells
        ),
    )
    for i, (nid, kind, block, text) in enumerate(parts, start=2):
        d.add_node(
            NodeDraft(
                id=nid,
                kind=kind,
                text=text,
                order=i,
                section=sec,
                depth=2,
                regions=_regions(reading, block),
                made_by=PART,
                source_blocks=[block],
                source_keys=[reading.block(block).key],
                table=table if kind is NodeKind.TABLE else None,
                marker="1" if kind is NodeKind.NOTE else None,
            ),
            stage=s,
        )
        d.add_edge(
            EdgeDraft(
                type=EdgeType.CONTAINS,
                source=sec,
                target=nid,
                basis=Basis.EXPLICIT,
                method="R-SEC-contains",
                made_by=CONTAINS,
            ),
            stage=s,
        )
    d.add_node(
        NodeDraft(
            id="t:annual",
            kind=NodeKind.TERM,
            text="Annual Fee",
            order=6,
            section=None,
            depth=0,
            regions=[],
            made_by=Maker(actor=Actor.RULE, id="R-LNK-term"),
        ),
        stage="link",
    )
    d.add_edge(
        EdgeDraft(
            type=EdgeType.CITES_NOTE,
            source="p:one",
            target="p:note",
            basis=Basis.EXPLICIT,
            method="R-INK-note",
            made_by=NOTE,
            label="1",
            evidence=Span.of(P1, 32, 33),
        ),
        stage=s,
    )
    d.add_unresolved(
        "p:one",
        Unresolved(kind="note", text="2", reason="no note labelled 2"),
        stage=s,
        maker=NOTE,
    )
    d.add_flag("p:one", Flag(code=FlagCode.NOTE_NOT_FOUND, detail="2"), stage=s, maker=NOTE)
    term_maker = Maker(actor=Actor.RULE, id="R-LNK-term")
    d.add_edge(
        EdgeDraft(
            type=EdgeType.DEFINES,
            source="p:two",
            target="t:annual",
            basis=Basis.EXPLICIT,
            method="R-LNK-term",
            made_by=term_maker,
            label="Annual Fee",
            evidence=Span.of(P2, 0, 10),
        ),
        stage="link",
    )
    d.add_edge(
        EdgeDraft(
            type=EdgeType.USES_TERM,
            source="p:one",
            target="t:annual",
            basis=Basis.EXPLICIT,
            method="R-LNK-term",
            made_by=term_maker,
            label="Annual Fee",
            evidence=Span.of(P1, 21, 31),
        ),
        stage="link",
    )
    d.add_role(
        "p:one",
        RoleDraft(
            role=Role.OBLIGATION,
            evidence=Span.of(P1, 8, 12),
            made_by=PART,
            basis=Basis.EXPLICIT,
        ),
        stage="classify",
    )
    d.add_role(
        "p:two",
        RoleDraft(
            role=Role.DEFINITION,
            evidence=Span.of(P2, 11, 16),
            made_by=CLASSIFY,
            basis=Basis.SEMANTIC,
        ),
        stage="agent_classify",
    )
    agent_edge = EdgeDraft(
        type=EdgeType.QUALIFIES,
        source="p:two",
        target="p:one",
        basis=Basis.SEMANTIC,
        method="A-relate",
        made_by=RELATE,
        evidence=Span.of(P2, 35, 49),
    )
    d.add_edge(agent_edge, stage="agent_relate")
    d.set_edge_verdict(
        agent_edge.id,
        Verdict(verdict="supported", model="m/verifier", request_key="rk-verify"),
        stage="agent_verify",
        maker=VERIFY,
    )
    return Sample(
        reading=reading,
        draft=d,
        doc=doc,
        section=sec,
        p1="p:one",
        p2="p:two",
        table="p:tab",
        note="p:note",
        term="t:annual",
        agent_edge=agent_edge.id,
    )
