"""Table cell labels (spec 02 § 6, `R-SEC-cells`)."""

from __future__ import annotations

from inkthread.domain.model import CellInfo, TableInfo
from inkthread.domain.reading import RCell, RGrid

CELLS = "R-SEC-cells"


def _cols(cell: RCell) -> range:
    return range(cell.col, cell.col + cell.col_span)


def _covers_row(cell: RCell, row: int) -> bool:
    return cell.row <= row < cell.row + cell.row_span


def _dedupe(texts: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for text in texts:
        if text and (not out or out[-1] != text):
            out.append(text)
    return tuple(out)


def _header_path(grid: RGrid, cell: RCell) -> tuple[str, ...]:
    cols = set(_cols(cell))
    heads = sorted(
        (c for c in grid.cells if c.row < grid.header_rows and cols & set(_cols(c))),
        key=lambda c: (c.row, c.col),
    )
    return _dedupe([c.text for c in heads])


def _row_labels(grid: RGrid, cell: RCell) -> tuple[str, ...]:
    labels: list[str] = []
    above = [r for r in grid.banner_rows if r < cell.row]
    if above:
        banner = max(above)
        labels += [
            c.text for c in sorted(grid.cells, key=lambda c: c.col) if c.row == banner and c.text
        ]
    left = sorted(
        (c for c in grid.cells if _covers_row(c, cell.row) and c.col + c.col_span <= cell.col),
        key=lambda c: c.col,
    )
    labels += [c.text for c in left if c.text and any(ch.isalpha() for ch in c.text)]
    return tuple(labels)


def cell_labels(grid: RGrid) -> tuple[CellInfo, ...]:
    """Every cell with its header flag, header path and row labels."""
    out: list[CellInfo] = []
    for cell in grid.cells:
        is_header = cell.row < grid.header_rows or cell.row in grid.banner_rows
        out.append(
            CellInfo(
                row=cell.row,
                col=cell.col,
                row_span=cell.row_span,
                col_span=cell.col_span,
                text=cell.text,
                is_header=is_header,
                header_path=() if is_header else _header_path(grid, cell),
                row_labels=() if is_header else _row_labels(grid, cell),
                markers=cell.markers,
                carried=cell.carried,
                page=cell.page,
                bbox=cell.bbox,
            )
        )
    return tuple(out)


def table_info(grid: RGrid) -> TableInfo:
    """The node's `table` field from inkgrid's grid."""
    return TableInfo(
        n_rows=grid.n_rows,
        n_cols=grid.n_cols,
        header_rows=grid.header_rows,
        banner_rows=grid.banner_rows,
        source=grid.source,
        cells=cell_labels(grid),
    )
