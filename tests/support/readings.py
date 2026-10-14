"""Literal `Reading` builders, so domain tests never need a PDF.

`ReadingBuilder` lays blocks out top to bottom on pages, aligns words to text the way inkgrid joins
them (one space), and assigns ids `b1`, `b2` … and keys `k<n>` in order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inkthread.domain.model import PageSize
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

SHA = "c" * 64


def words_for(
    text: str,
    page: int,
    y: float,
    *,
    hidden: set[str] | None = None,
    superscript: set[str] | None = None,
) -> tuple[RWord, ...]:
    """Words aligned to `text`, laid along one line at `y`."""
    out: list[RWord] = []
    cursor = 0
    x = 72.0
    for token in text.split():
        start = text.index(token, cursor)
        end = start + len(token)
        cursor = end
        out.append(
            RWord(
                start=start,
                end=end,
                page=page,
                bbox=(x, y, x + 6.0 * len(token), y + 10.0),
                hidden=bool(hidden and token in hidden),
                superscript=bool(superscript and token in superscript),
                text=token,
            )
        )
        x += 6.0 * len(token) + 3.0
    return tuple(out)


@dataclass
class ReadingBuilder:
    """Accumulates blocks; `build()` returns the frozen Reading."""

    pages: int = 1
    file_name: str | None = "doc.pdf"
    blocks: list[RBlock] = field(default_factory=list)
    links: list[RLink] = field(default_factory=list)
    findings: list[RFinding] = field(default_factory=list)
    defects: list[RDefect] = field(default_factory=list)
    _y: dict[int, float] = field(default_factory=dict)

    def add(
        self,
        kind: str,
        text: str,
        *,
        page: int = 1,
        height: float = 12.0,
        gap: float = 6.0,
        **extra: Any,
    ) -> str:
        """Append a block below the previous one on `page`; returns its id."""
        y = self._y.get(page, 72.0)
        self._y[page] = y + height + gap
        bid = f"b{len(self.blocks) + 1}"
        hidden = extra.pop("hidden", None)
        superscript = extra.pop("superscript", None)
        words = extra.pop("words", None)
        self.blocks.append(
            RBlock(
                id=bid,
                key=f"k{len(self.blocks) + 1:016x}",
                kind=kind,  # type: ignore[arg-type]
                text=text,
                regions=(RRegion(page=page, bbox=(72.0, y, 540.0, y + height)),),
                words=words
                if words is not None
                else words_for(text, page, y, hidden=hidden, superscript=superscript),
                **extra,
            )
        )
        return bid

    def heading(
        self, text: str, *, level: int = 1, number: str | None = None, page: int = 1, **extra: Any
    ) -> str:
        return self.add("heading", text, level=level, number=number, page=page, **extra)

    def para(self, text: str, *, page: int = 1, **extra: Any) -> str:
        return self.add("paragraph", text, page=page, **extra)

    def item(self, text: str, *, label: str, page: int = 1) -> str:
        return self.add("list_item", text, label=label, page=page)

    def note(self, text: str, *, label: str, page: int = 1) -> str:
        return self.add("footnote", text, label=label, page=page)

    def definition(self, term: str, body: str, *, page: int = 1) -> str:
        return self.add("definition", f"{term} {body}", term=term, body=body, page=page)

    def furniture(self, text: str, *, role: str = "header", page: int = 1) -> str:
        return self.add("furniture", text, role=role, page=page)

    def table(
        self,
        rows: list[list[str]],
        *,
        header_rows: int = 1,
        page: int = 1,
        banner_rows: tuple[int, ...] = (),
        spans: dict[tuple[int, int], int] | None = None,
        source: str = "lattice",
    ) -> str:
        """A grid from row lists; `spans` maps (row, col) to a column span (cells it covers are
        omitted from `rows`' accounting by the caller)."""
        spans = spans or {}
        cells: list[RCell] = []
        n_cols = max(
            sum(spans.get((r, c), 1) for c in range(len(row))) for r, row in enumerate(rows)
        )
        for r, row in enumerate(rows):
            col = 0
            for c, text in enumerate(row):
                span = spans.get((r, c), 1)
                cells.append(
                    RCell(
                        row=r,
                        col=col,
                        row_span=1,
                        col_span=span,
                        text=text,
                        page=page,
                        bbox=(
                            72.0 + 60 * col,
                            100.0 + 14 * r,
                            72.0 + 60 * (col + span),
                            114.0 + 14 * r,
                        ),
                    )
                )
                col += span
        text = "\n".join(" ".join(t for t in row if t) for row in rows)
        grid = RGrid(
            n_rows=len(rows),
            n_cols=n_cols,
            header_rows=header_rows,
            banner_rows=banner_rows,
            source=source,  # type: ignore[arg-type]
            cells=tuple(cells),
        )
        return self.add("table", text, page=page, height=14.0 * len(rows), grid=grid)

    def call(
        self,
        from_block: str,
        to_block: str | None,
        label: str,
        *,
        method: str = "superscript",
        status: str = "resolved",
        cell: tuple[int, int] | None = None,
    ) -> None:
        self.links.append(
            RLink(
                kind="footnote_call",
                from_block=from_block,
                from_cell=cell,
                to_block=to_block,
                label=label,
                method=method,  # type: ignore[arg-type]
                status=status,
            )
        )  # type: ignore[arg-type]

    def continuation(self, child: str, parent: str) -> None:
        self.links.append(
            RLink(kind="continuation", from_block=child, to_block=parent, status="resolved")
        )

    def build(self, *, sha: str = SHA) -> Reading:
        return Reading(
            sha256=sha,
            file_name=self.file_name,
            pages=tuple(
                PageSize(number=n, width=612.0, height=792.0) for n in range(1, self.pages + 1)
            ),
            blocks=tuple(self.blocks),
            links=tuple(self.links),
            findings=tuple(self.findings),
            defects=tuple(self.defects),
            producer={"inkgrid": "0.1.0"},
            verified=True,
        )
