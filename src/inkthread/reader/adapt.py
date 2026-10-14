"""Build the domain's `Reading` from inkgrid's `Document` and `VerificationReport` (spec 02 § 1)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

import inkgrid
from inkgrid.model.geometry import unturn_rect

from inkthread.domain.model import Bbox, PageSize
from inkthread.domain.reading import (
    RBlock,
    RCell,
    RDefect,
    Reading,
    RFinding,
    RGrid,
    RLink,
    RRegion,
    RWord,
)


class WordLike(Protocol):
    """The fields of an inkgrid word that alignment reads."""

    @property
    def id(self) -> int: ...
    @property
    def page(self) -> int: ...
    @property
    def bbox(self) -> inkgrid.Rect: ...
    @property
    def text(self) -> str: ...
    @property
    def hidden(self) -> bool: ...
    @property
    def superscript(self) -> bool: ...


def _bbox(rect: inkgrid.Rect) -> Bbox:
    return (rect.x0, rect.y0, rect.x1, rect.y1)


def _overlaps(start: int, end: int, claimed: Iterable[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in claimed)


def _unclaimed(text: str, token: str, claimed: list[tuple[int, int]]) -> int | None:
    at = text.find(token)
    while at != -1:
        if not _overlaps(at, at + len(token), claimed):
            return at
        at = text.find(token, at + 1)
    return None


def align_words(
    text: str, words: Sequence[WordLike], hyphen_joins: Iterable[tuple[int, int]]
) -> list[RWord]:
    """Each word's offsets in `text` (spec 02 § 1.1); `start = end = None` when it is not found.

    A forward search from a cursor; the left word of a hyphen join is sought without its trailing
    hyphen; a word not found forward is sought from the start among unclaimed offsets.
    """
    join_left = {a for a, _ in hyphen_joins}
    claimed: list[tuple[int, int]] = []
    cursor = 0
    out: list[RWord] = []
    for w in words:
        token = w.text
        if w.id in join_left and token.endswith("-") and len(token) > 1:
            token = token[:-1]
        start: int | None = None
        if token:
            at = text.find(token, cursor)
            if at != -1 and not _overlaps(at, at + len(token), claimed):
                start = at
                cursor = at + len(token)
            else:
                start = _unclaimed(text, token, claimed)
        end = None if start is None else start + len(token)
        if start is not None and end is not None:
            claimed.append((start, end))
        out.append(
            RWord(
                start=start,
                end=end,
                page=w.page,
                bbox=_bbox(w.bbox),
                hidden=w.hidden,
                superscript=w.superscript,
                text=w.text,
            )
        )
    return out


def _grid(table: inkgrid.Table, pages: dict[int, inkgrid.PageInfo]) -> RGrid:
    grid = table.grid
    page_no = table.regions[0].page
    page = pages[page_no]
    cells: list[RCell] = []
    for cell in grid.cells:
        rect = grid.cell_rect(cell)
        if grid.frame != 0:
            rect = unturn_rect(rect, grid.frame, page.width, page.height)
        cells.append(
            RCell(
                row=cell.row,
                col=cell.col,
                row_span=cell.row_span,
                col_span=cell.col_span,
                text=cell.text,
                carried=cell.carried,
                markers=tuple(cell.markers),
                page=page_no,
                bbox=_bbox(rect),
            )
        )
    return RGrid(
        n_rows=grid.n_rows,
        n_cols=grid.n_cols,
        header_rows=grid.header_rows,
        banner_rows=tuple(grid.banner_rows),
        source=grid.source,
        cells=tuple(cells),
    )


def _block(
    block: inkgrid.Block, words: dict[int, inkgrid.Word], pages: dict[int, inkgrid.PageInfo]
) -> RBlock:
    fields: dict[str, object] = {
        "id": block.id,
        "key": block.key,
        "kind": block.kind,
        "text": block.text,
        "regions": tuple(RRegion(page=r.page, bbox=_bbox(r.bbox)) for r in block.regions),
        "words": tuple(
            align_words(block.text, [words[i] for i in block.word_ids], block.hyphen_joins)
        ),
        "markers": tuple(block.markers),
    }
    match block:
        case inkgrid.Heading():
            fields |= {"level": block.level, "number": block.number}
        case inkgrid.ListItem() | inkgrid.Footnote():
            fields |= {"label": block.label}
        case inkgrid.Definition():
            fields |= {"term": block.term, "body": block.body}
        case inkgrid.Furniture():
            fields |= {"role": block.role}
        case inkgrid.Table():
            fields |= {"grid": _grid(block, pages)}
        case inkgrid.Paragraph():
            pass
    return RBlock.model_validate(fields)


def _link(link: inkgrid.Link) -> RLink:
    return RLink(
        kind=link.kind,
        from_block=link.from_.block,
        from_cell=link.from_.cell,
        to_block=link.to,
        label=link.label,
        method=link.method,
        status=link.status,
        reason=link.reason,
    )


def _defect(defect: inkgrid.Defect) -> RDefect:
    return RDefect(
        code=str(defect.code),
        block=defect.block,
        cell=defect.cell,
        page=defect.page,
        detail=defect.detail,
    )


def adapt(document: inkgrid.Document, report: inkgrid.VerificationReport | None) -> Reading:
    """The domain's view of one inkgrid reading; `verified` when a report was given."""
    words = {w.id: w for w in document.words}
    pages = {p.number: p for p in document.pages}
    producer: dict[str, str | None] = {
        name: (None if value is None else str(value))
        for name, value in document.producer.model_dump().items()
    }
    return Reading(
        sha256=document.source.sha256,
        file_name=document.source.file_name,
        pages=tuple(
            PageSize(number=p.number, width=p.width, height=p.height) for p in pages.values()
        ),
        blocks=tuple(_block(b, words, pages) for b in document.blocks),
        links=tuple(_link(link) for link in document.links),
        findings=tuple(
            RFinding(code=str(f.code), severity=str(f.severity), page=f.page, detail=f.detail)
            for f in document.findings
        ),
        defects=() if report is None else tuple(_defect(d) for d in report.defects),
        producer=producer,
        verified=report is not None,
    )
