"""Where each block's text sits inside its node's text."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BlockPlace:
    """A block's node and the offset of its text in the node's text.

    `offset` is None when the block's offsets do not index the node's text (a repeated title whose
    text differs from the title's in whitespace).
    """

    node: str
    offset: int | None
