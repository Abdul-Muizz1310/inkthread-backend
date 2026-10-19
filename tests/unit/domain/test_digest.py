"""Spec 11 cases: the reading digest's invariants (T-RD-5) and table node ids (T-RD-6)."""

from __future__ import annotations

from typing import Any

import pytest
from graphs import edge, graph, minimal_parts, node
from pydantic import ValidationError

from inkthread.domain.digest import (
    DefectNote,
    FindingNote,
    ReadingDigest,
    TableDigest,
    VerificationSummary,
    link_tables,
)
from inkthread.domain.model import CellInfo, EdgeType, NodeKind, NodeSource, TableInfo

CLEAN = {"ok": True, "engine": "pdfium 7417 (pypdfium2 5.13.0)", "checked": 1, "disagreements": 0}


def table(tid: str = "b2", **overrides: Any) -> TableDigest:
    fields: dict[str, Any] = {
        "id": tid,
        "page": 1,
        "bbox": (72.0, 100.0, 300.0, 160.0),
        "header_rows": 1,
        "rows": (("Fee", "Amount"), ("Filing", "$350")),
        "markdown": "| Fee | Amount |\n| --- | --- |\n| Filing | $350 |",
    }
    return TableDigest(**{**fields, **overrides})


def digest(*tables: TableDigest) -> ReadingDigest:
    return ReadingDigest(
        inkgrid_version="0.2.0",
        verification=VerificationSummary(**CLEAN),
        tables=tables,
        findings=(FindingNote(code="hidden_text", severity="warning", page=None),),
    )


def test_a_consistent_digest_builds() -> None:
    d = digest(table("b2"), table("b5"))
    assert [t.id for t in d.tables] == ["b2", "b5"]
    assert d.findings[0].page is None


def test_T_RD_5_disagreements_must_count_the_defects() -> None:
    defect = DefectNote(code="lost", page=1, message="2 characters lost")
    with pytest.raises(ValidationError, match="disagreements"):
        VerificationSummary(**{**CLEAN, "ok": False, "disagreements": 2, "defects": (defect,)})
    assert VerificationSummary(**{**CLEAN, "ok": False, "disagreements": 1, "defects": (defect,)})


@pytest.mark.parametrize(
    ("ok", "defects"),
    [(True, (DefectNote(code="lost", page=1, message="x"),)), (False, ())],
)
def test_T_RD_5_ok_is_exactly_no_defects(ok: bool, defects: tuple[DefectNote, ...]) -> None:
    with pytest.raises(ValidationError, match="ok"):
        VerificationSummary(
            **{**CLEAN, "ok": ok, "disagreements": len(defects), "defects": defects}
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"rows": (("Fee", "Amount"), ("Filing",))},  # ragged
        {"rows": ()},  # no rows
        {"rows": ((),)},  # an empty row
        {"header_rows": 3},  # more header rows than rows
        {"header_rows": -1},
        {"id": "t1"},  # not an inkgrid block id
        {"page": 0},
        {"markdown": ""},
    ],
)
def test_T_RD_5_a_malformed_table_is_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        table(**overrides)


def test_T_RD_5_table_ids_are_unique() -> None:
    with pytest.raises(ValidationError, match="twice"):
        digest(table("b2"), table("b2"))


@pytest.mark.parametrize("field", [{"checked": -1}, {"disagreements": -1}, {"engine": ""}])
def test_T_RD_5_counts_and_engine_are_sane(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VerificationSummary(**{**CLEAN, **field})


def test_T_RD_5_the_version_is_named() -> None:
    with pytest.raises(ValidationError):
        ReadingDigest(inkgrid_version="", verification=VerificationSummary(**CLEAN))


def _table_node(nid: str, block: str, order: int) -> Any:
    cell = CellInfo(
        row=0,
        col=0,
        row_span=1,
        col_span=1,
        text="Fee",
        is_header=True,
        header_path=(),
        row_labels=(),
        markers=(),
        carried=False,
        page=1,
        bbox=None,
    )
    info = TableInfo(
        n_rows=1, n_cols=1, header_rows=1, banner_rows=(), source="lattice", cells=(cell,)
    )
    return node(
        nid,
        NodeKind.TABLE,
        "Fee",
        order,
        "s:one",
        2,
        table=info,
        source=NodeSource(blocks=(block,), keys=()),
    )


def test_T_RD_6_a_table_gets_the_node_that_cites_its_block() -> None:
    nodes, edges = minimal_parts()
    nodes.append(_table_node("t:fees", "b2", 3))
    edges.append(edge(EdgeType.CONTAINS, "s:one", "t:fees"))
    g = graph(nodes, edges)
    linked = link_tables(digest(table("b2"), table("b9")), g)
    assert [(t.id, t.node_id) for t in linked] == [("b2", "t:fees"), ("b9", None)]
    # Everything else is carried over unchanged.
    assert linked[0].rows == table("b2").rows
    assert linked[0].markdown == table("b2").markdown


def test_T_RD_6_only_table_nodes_count() -> None:
    nodes, edges = minimal_parts()  # p:one cites b2 but is a paragraph
    g = graph(nodes, edges)
    (linked,) = link_tables(digest(table("b2")), g)
    assert linked.node_id is None
