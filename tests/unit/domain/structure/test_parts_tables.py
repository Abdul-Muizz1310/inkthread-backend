"""Spec 02 § 6: parts and table cells (T-ST-22..26) and a table-only document."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.draft import GraphDraft
from inkthread.domain.model import Actor, FlagCode, NodeKind
from inkthread.domain.reading import RGrid
from inkthread.domain.structure.build import build_structure
from inkthread.domain.structure.tables import cell_labels


def run(b: ReadingBuilder) -> GraphDraft:
    reading = b.build()
    draft = GraphDraft(sha256=reading.sha256, pipeline_version="1.0.0")
    build_structure(reading, draft)
    return draft


def grid_of(b: ReadingBuilder, bid: str) -> RGrid:
    grid = b.build().block(bid).grid
    assert grid is not None
    return grid


def test_each_kind_maps_to_its_node_kind() -> None:  # T-ST-22
    b = ReadingBuilder()
    b.para("A paragraph.")
    b.item("An item.", label="(a)")
    b.note("A note.", label="1")
    b.definition("Fee", "means money.")
    b.table([["H"], ["v"]])
    draft = run(b)
    got = {n.text: (n.kind, n.marker) for n in draft.nodes.values() if n.kind != "document"}
    assert got == {
        "A paragraph.": (NodeKind.PARAGRAPH, None),
        "An item.": (NodeKind.LIST_ITEM, "(a)"),
        "A note.": (NodeKind.NOTE, "1"),
        "Fee means money.": (NodeKind.DEFINITION, None),
        "H\nv": (NodeKind.TABLE, None),
    }
    para = draft.nodes_of(NodeKind.PARAGRAPH)[0]
    assert para.source_blocks == ["b1"]
    assert para.source_keys == [b.blocks[0].key]
    assert para.made_by.actor is Actor.INKGRID
    assert [(r.page, r.bbox) for r in para.regions] == [(1, b.blocks[0].regions[0].bbox)]


def test_two_header_rows_give_a_path_top_first() -> None:  # T-ST-23
    b = ReadingBuilder()
    t = b.table([["Fees", "Fees"], ["Item", "Amount"], ["Filing", "$5"]], header_rows=2)
    cells = {(c.row, c.col): c for c in cell_labels(grid_of(b, t))}
    assert cells[(0, 0)].is_header
    assert cells[(1, 1)].is_header
    value = cells[(2, 1)]
    assert not value.is_header
    assert value.header_path == ("Fees", "Amount")
    assert cells[(0, 0)].header_path == ()


def test_spanning_header_covers_its_columns() -> None:  # T-ST-24
    b = ReadingBuilder()
    t = b.table(
        [["Charges"], ["Initial", "Annual"], ["$1", "$2"]],
        header_rows=2,
        spans={(0, 0): 2},
    )
    cells = {(c.row, c.col): c for c in cell_labels(grid_of(b, t))}
    assert cells[(2, 0)].header_path == ("Charges", "Initial")
    assert cells[(2, 1)].header_path == ("Charges", "Annual")


def test_row_labels_take_banner_and_lettered_cells() -> None:  # T-ST-25
    b = ReadingBuilder()
    t = b.table(
        [
            ["Item", "Code", "Amount"],
            ["Annual fees"],
            ["Listing", "12", "$5"],
        ],
        header_rows=1,
        banner_rows=(1,),
        spans={(1, 0): 3},
    )
    cells = {(c.row, c.col): c for c in cell_labels(grid_of(b, t))}
    assert cells[(1, 0)].is_header
    value = cells[(2, 2)]
    assert value.row_labels == ("Annual fees", "Listing")
    assert value.header_path == ("Amount",)
    assert cells[(2, 0)].row_labels == ("Annual fees",)


def test_no_header_rows_flags_the_table() -> None:  # T-ST-26
    b = ReadingBuilder()
    b.table([["a", "1"], ["b", "2"]], header_rows=0)
    table = run(b).nodes_of(NodeKind.TABLE)[0]
    assert [f.code for f in table.flags] == [FlagCode.HEADER_NOT_FOUND]
    assert table.table is not None
    assert all(not c.is_header and c.header_path == () for c in table.table.cells)


def test_table_only_document() -> None:  # plan review focus 2
    b = ReadingBuilder()
    b.table([["Fee", "Amount"], ["Filing", "$350.00"]])
    draft = run(b)
    assert [n.kind for n in draft.nodes.values()] == [NodeKind.DOCUMENT, NodeKind.TABLE]
    table = draft.nodes_of(NodeKind.TABLE)[0]
    assert table.flags == []
    assert table.table is not None
    assert (table.table.n_rows, table.table.n_cols, table.table.header_rows) == (2, 2, 1)
    assert table.text == "Fee Amount\nFiling $350.00"
    assert table.section == draft.nodes_of(NodeKind.DOCUMENT)[0].id
