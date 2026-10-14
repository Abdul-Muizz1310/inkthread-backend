"""Spec 01: the graph contract and its invariants (T-GC-1, 2, 5, 7-18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from graphs import INK, OK, RULE, edge, graph, minimal_parts, node
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from inkthread.domain.model import (
    Actor,
    Basis,
    CellInfo,
    Edge,
    EdgeType,
    Graph,
    Maker,
    NodeKind,
    Span,
    TableInfo,
)

SCHEMA = Path(__file__).resolve().parents[3] / "docs" / "schema" / "graph.schema.json"


def test_minimal_graph_round_trips() -> None:  # T-GC-1
    g = graph(*minimal_parts())
    data = g.model_dump_json(by_alias=True)
    assert json.loads(data)["schema"] == "inkthread.graph/1"
    assert Graph.model_validate_json(data) == g


def test_schema_is_pinned() -> None:  # T-GC-2
    current = json.dumps(Graph.model_json_schema(by_alias=True), indent=2, sort_keys=True) + "\n"
    assert SCHEMA.read_text(encoding="utf-8") == current


def test_duplicate_edges_collapse_by_id() -> None:  # T-GC-5
    a = edge(EdgeType.CONTAINS, "s:one", "p:one")
    b = edge(EdgeType.CONTAINS, "s:one", "p:one")
    assert a.id == b.id


@given(st.text(min_size=1, max_size=200), st.data())
def test_span_quote_is_the_slice(text: str, data: st.DataObject) -> None:  # T-GC-7
    start = data.draw(st.integers(0, len(text) - 1))
    end = data.draw(st.integers(start + 1, len(text)))
    assert Span.of(text, start, end).quote == text[start:end]


def test_duplicate_node_id() -> None:  # T-GC-8
    nodes, edges = minimal_parts()
    with pytest.raises(ValidationError, match="duplicate node id"):
        graph([*nodes, nodes[2]], edges)


def test_edge_to_missing_node() -> None:  # T-GC-9
    nodes, edges = minimal_parts()
    with pytest.raises(ValidationError, match="unknown node"):
        graph(nodes, [*edges, edge(EdgeType.REFERS_TO, "p:one", "p:ghost", "R-REF-section")])


def test_self_loop() -> None:  # T-GC-10
    with pytest.raises(ValidationError):
        edge(EdgeType.REFERS_TO, "p:one", "p:one", "R-REF-section")


def test_exactly_one_document() -> None:  # T-GC-11
    nodes, edges = minimal_parts()
    with pytest.raises(ValidationError, match="document"):
        graph(nodes[1:], edges[1:])
    extra = node("d:two", NodeKind.DOCUMENT, "", 0, None, 0)
    with pytest.raises(ValidationError, match="document"):
        graph([*nodes, extra], edges)


def test_contains_tree() -> None:  # T-GC-12
    nodes, edges = minimal_parts()
    with pytest.raises(ValidationError, match="contains"):
        graph(nodes, edges[:1])
    second = edge(EdgeType.CONTAINS, "d:doc", "p:one")
    with pytest.raises(ValidationError, match="contains"):
        graph(nodes, [*edges, second])


def test_bad_span() -> None:  # T-GC-13
    with pytest.raises(ValidationError):
        Span(start=0, end=3, quote="xy")
    with pytest.raises(ValueError, match="span"):
        Span.of("abc", 2, 9)
    nodes, edges = minimal_parts()
    bad = edge(EdgeType.CONTAINS, "s:one", "p:one", evidence=Span(start=0, end=4, quote="Nope"))
    with pytest.raises(ValidationError, match="evidence"):
        graph(nodes, [edges[0], bad])


def test_typed_targets() -> None:  # T-GC-14
    nodes, edges = minimal_parts()
    with pytest.raises(ValidationError, match="cites_note"):
        graph(
            nodes,
            [*edges, edge(EdgeType.CITES_NOTE, "s:one", "p:one", "R-INK-note", made_by=INK)],
        )


def test_table_field_matches_kind() -> None:  # T-GC-15
    with pytest.raises(ValidationError, match="table"):
        node("p:t", NodeKind.TABLE, "x", 3, "s:one", 2)
    info = TableInfo(
        n_rows=1,
        n_cols=1,
        header_rows=0,
        banner_rows=(),
        source="corridor",
        cells=(
            CellInfo(
                row=0,
                col=0,
                row_span=1,
                col_span=1,
                text="x",
                is_header=False,
                header_path=(),
                row_labels=(),
                markers=(),
                carried=False,
                page=1,
                bbox=None,
            ),
        ),
    )
    with pytest.raises(ValidationError, match="table"):
        node("p:x", NodeKind.PARAGRAPH, "x", 3, "s:one", 2, table=info)
    assert node("p:t", NodeKind.TABLE, "x", 3, "s:one", 2, table=info).table == info


def test_semantic_basis_needs_an_agent() -> None:  # T-GC-16
    with pytest.raises(ValidationError, match="semantic"):
        Edge.make(
            type=EdgeType.QUALIFIES,
            source="p:a",
            target="p:b",
            basis=Basis.SEMANTIC,
            method="R-X",
            made_by=RULE,
            confidence=OK,
        )
    with pytest.raises(ValidationError, match="model"):
        Maker(actor=Actor.AGENT, id="A-relate")
    with pytest.raises(ValidationError, match="model"):
        Maker(actor=Actor.RULE, id="R-X", model="m", request_key="k")


def test_unknown_vocabulary() -> None:  # T-GC-17
    with pytest.raises(ValidationError):
        node("p:x", "chapter", "x", 3, "s:one", 2)  # type: ignore[arg-type]
    with pytest.raises(ValueError):  # noqa: PT011
        EdgeType("related")


def test_cells_tile_the_grid() -> None:  # T-GC-18
    def cell(r: int, c: int, rs: int = 1, cs: int = 1) -> CellInfo:
        return CellInfo(
            row=r,
            col=c,
            row_span=rs,
            col_span=cs,
            text="",
            is_header=False,
            header_path=(),
            row_labels=(),
            markers=(),
            carried=False,
            page=1,
            bbox=None,
        )

    with pytest.raises(ValidationError, match="tile"):
        TableInfo(
            n_rows=1, n_cols=2, header_rows=0, banner_rows=(), source="lattice", cells=(cell(0, 0),)
        )
    with pytest.raises(ValidationError, match="tile"):
        TableInfo(
            n_rows=1,
            n_cols=2,
            header_rows=0,
            banner_rows=(),
            source="lattice",
            cells=(cell(0, 0, cs=2), cell(0, 1)),
        )
    ok = TableInfo(
        n_rows=1,
        n_cols=2,
        header_rows=0,
        banner_rows=(),
        source="lattice",
        cells=(cell(0, 0), cell(0, 1)),
    )
    assert len(ok.cells) == 2
