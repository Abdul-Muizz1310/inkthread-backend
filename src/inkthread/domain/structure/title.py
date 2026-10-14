"""The document's title (spec 02 § 3, `R-SEC-title`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from inkthread.domain.ids import fold
from inkthread.domain.reading import RBlock

TITLE = "R-SEC-title"


TITLE_WINDOW = 3


@dataclass(frozen=True)
class TitleResult:
    """The title's lines (one or more same-size headings) and the later headings that repeat them."""

    lines: tuple[RBlock, ...] = ()
    repeats: tuple[RBlock, ...] = ()

    @property
    def block(self) -> RBlock | None:
        """The title's first line."""
        return self.lines[0] if self.lines else None

    @property
    def text(self) -> str:
        """The title as printed, lines joined by newlines."""
        return "\n".join(b.text for b in self.lines)

    @property
    def block_ids(self) -> tuple[str, ...]:
        """Every block the document node cites: the title's lines, then its repeats."""
        return (*(b.id for b in self.lines), *(b.id for b in self.repeats))


def find_title(blocks: Sequence[RBlock]) -> TitleResult:
    """The title: a heading of the document's largest type among the first content blocks of
    page 1, plus the same-size heading lines directly under it; and the later headings that
    repeat any of those lines (a cover page printed twice).

    `blocks` are the content blocks (set-aside removed) in reading order.
    """
    headings = [b for b in blocks if b.kind == "heading" and b.level is not None]
    if not headings:
        return TitleResult()
    top = min(b.level for b in headings if b.level is not None)
    first_page = [b for b in blocks if b.page == 1][:TITLE_WINDOW]
    title = next((b for b in first_page if b.kind == "heading" and b.level == top), None)
    if title is None:
        return TitleResult()
    at = blocks.index(title)
    lines = [title]
    for b in blocks[at + 1 :]:
        if b.kind == "heading" and b.level == top and b.page == title.page and not b.number:
            lines.append(b)
        else:
            break
    keys = {fold(b.text) for b in lines}
    after = blocks[at + len(lines) :]
    repeats = tuple(
        b
        for b in after
        if b.kind == "heading" and b.page <= title.page + 2 and fold(b.text) in keys
    )
    return TitleResult(lines=tuple(lines), repeats=repeats)
