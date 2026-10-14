"""The document's title (spec 02 § 3, `R-SEC-title`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from inkthread.domain.ids import fold
from inkthread.domain.reading import RBlock

TITLE = "R-SEC-title"


@dataclass(frozen=True)
class TitleResult:
    """The title block (or None) and the later headings that repeat it."""

    block: RBlock | None
    repeats: tuple[RBlock, ...] = ()

    @property
    def block_ids(self) -> tuple[str, ...]:
        """Every block the document node cites: the title, then its repeats."""
        if self.block is None:
            return ()
        return (self.block.id, *(b.id for b in self.repeats))


def find_title(blocks: Sequence[RBlock]) -> TitleResult:
    """The first page-1 heading of the document's smallest heading level, and its repeats.

    `blocks` are the content blocks (set-aside removed) in reading order.
    """
    headings = [b for b in blocks if b.kind == "heading" and b.level is not None]
    if not headings:
        return TitleResult(block=None)
    top = min(b.level for b in headings if b.level is not None)
    title = next((b for b in headings if b.level == top and b.page == 1), None)
    if title is None:
        return TitleResult(block=None)
    key = fold(title.text)
    after = blocks[blocks.index(title) + 1 :]
    repeats = tuple(b for b in after if b.kind == "heading" and fold(b.text) == key)
    return TitleResult(block=title, repeats=repeats)
