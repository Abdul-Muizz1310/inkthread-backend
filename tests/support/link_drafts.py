"""Literal `GraphDraft` builders for the classify and link stage tests."""

from __future__ import annotations

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.ids import document_id, part_id, section_id
from inkthread.domain.model import (
    Actor,
    CellInfo,
    EdgeType,
    EvidenceSide,
    Maker,
    NodeKind,
    Region,
    Span,
    TableInfo,
)
from inkthread.domain.structure.types import SectionIndex

SHA = "b" * 64
INK = Maker(actor=Actor.INKGRID, id="inkgrid")
REGION = Region(page=1, bbox=(10.0, 10.0, 100.0, 20.0))


class DraftBuilder:
    """Adds a document, sections and parts in reading order, and keeps a section index."""

    def __init__(self, title: str = "Test Document") -> None:
        self.draft = GraphDraft(sha256=SHA, pipeline_version="test")
        self.sections = SectionIndex()
        self.doc = document_id(SHA)
        self.draft.add_node(
            NodeDraft(
                id=self.doc,
                kind=NodeKind.DOCUMENT,
                text="",
                order=0,
                section=None,
                depth=0,
                regions=[],
                made_by=INK,
                label=title,
            ),
            stage="test",
        )
        self._order = 0
        self.current = self.doc
        self._titles: dict[str, list[str]] = {self.doc: []}
        self._depth: dict[str, int] = {self.doc: 0}

    def _next(self) -> int:
        self._order += 1
        return self._order

    def section(
        self,
        text: str,
        number: str | None = None,
        *,
        counter: str = "num",
        parent: str | None = None,
    ) -> str:
        """Add a section heading under `parent` (default: the document) and make it current."""
        parent = parent or self.doc
        titles = self._titles[parent]
        sid = section_id(titles, text)
        depth = self._depth[parent] + 1
        self.draft.add_node(
            NodeDraft(
                id=sid,
                kind=NodeKind.SECTION,
                text=text,
                order=self._next(),
                section=parent,
                depth=depth,
                regions=[REGION],
                made_by=INK,
            ),
            stage="test",
        )
        self._titles[sid] = [*titles, text]
        self._depth[sid] = depth
        if number is not None:
            self.sections.by_key[counter, number] = sid
            self.sections.numbers[sid] = number
        self.current = sid
        return sid

    def part(
        self,
        text: str,
        kind: NodeKind = NodeKind.PARAGRAPH,
        *,
        marker: str | None = None,
        table: TableInfo | None = None,
        hidden: tuple[tuple[int, int], ...] = (),
        section: str | None = None,
    ) -> str:
        """Add a content part to `section` (default: the current section)."""
        sec = section or self.current
        pid = part_id(kind.value, self._titles[sec], text) + f"#{self._order + 1}"
        self.draft.add_node(
            NodeDraft(
                id=pid,
                kind=kind,
                text=text,
                order=self._next(),
                section=sec,
                depth=self._depth[sec] + 1,
                regions=[REGION],
                made_by=INK,
                marker=marker,
                table=table,
                hidden_spans=[Span.of(text, s, e) for s, e in hidden],
            ),
            stage="test",
        )
        return pid

    def table(self, rows: list[list[str]], *, header_rows: int = 1) -> str:
        """Add a table whose text is its cells, tab-separated, one row per line."""
        cells = tuple(
            CellInfo(
                row=r,
                col=c,
                row_span=1,
                col_span=1,
                text=value,
                is_header=r < header_rows,
                page=1,
            )
            for r, row in enumerate(rows)
            for c, value in enumerate(row)
        )
        info = TableInfo(
            n_rows=len(rows),
            n_cols=len(rows[0]),
            header_rows=header_rows,
            source="lattice",
            cells=cells,
        )
        text = "\n".join("\t".join(row) for row in rows)
        return self.part(text, NodeKind.TABLE, table=info)


def edges_of(draft: GraphDraft, etype: EdgeType) -> list[EdgeDraft]:
    """The draft's edges of one type, in insertion order."""
    return [e for e in draft.edges.values() if e.type is etype]


def evidence_fits(draft: GraphDraft, edge: EdgeDraft) -> bool:
    """Spec 01 § 7 invariant 6 for one edge."""
    if edge.evidence is None:
        return True
    side = edge.source if edge.evidence_on is EvidenceSide.SOURCE else edge.target
    return edge.evidence.fits(draft.node(side).text)
