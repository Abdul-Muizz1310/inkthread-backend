"""Set-aside (spec 02 § 2): furniture and tables of contents are kept outside the graph's nodes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from inkthread.domain.ids import fold
from inkthread.domain.model import SetAside
from inkthread.domain.reading import RBlock
from inkthread.domain.text import finditer_words

FURNITURE = "R-SET-furniture"
TOC = "R-SET-toc"

TOC_HEADINGS = frozenset(
    {"contents", "table of contents", "list of tables", "list of figures", "list of exhibits"}
)
_TOC_LINE_KINDS = frozenset({"heading", "paragraph", "list_item"})
_TOC_LINE_LIMIT = 160
_ROMAN = r"(?=[ivxlcdm])m{0,4}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})"
_PAGE_REF = re.compile(rf"(?:^|[\s.…·])(\d{{1,4}}|{_ROMAN})$")
_MODAL = r"shall|must|may|will"
_BODY_WORDS = 40
_RUN_MIN = 3
_RUN_MIN_AFTER_HEADING = 2
_HEADING_REACH = 3


def page_reference(text: str) -> str | None:
    """The page reference a line ends in (an Arabic number up to 4 digits or a lowercase Roman
    numeral, optionally after leader dots), or None."""
    match = _PAGE_REF.search(text.rstrip())
    return match.group(1) if match else None


_ENTRY = re.compile(r"[A-Za-z).:]\s+\d{1,4}(?=\s+\S|$)")
_FUSED_MIN = 2
_WORDS_PER_ENTRY = 16


def is_toc_line(block: RBlock) -> bool:
    """A heading, paragraph or list item ending in a page reference with no modal verb: either
    short (one entry) or several entries fused into one block, each a title then its page."""
    if block.kind not in _TOC_LINE_KINDS or page_reference(block.text) is None:
        return False
    if next(finditer_words(_MODAL, block.text), None) is not None:
        return False
    if len(block.text) <= _TOC_LINE_LIMIT:
        return True
    entries = len(_ENTRY.findall(block.text))
    return entries >= _FUSED_MIN and entries * _WORDS_PER_ENTRY >= len(block.text.split())


def is_toc_heading(block: RBlock) -> bool:
    """A heading that reads `contents`, `table of contents`, `list of tables` … (any case)."""
    return block.kind == "heading" and fold(block.text).casefold() in TOC_HEADINGS


def _entry(block: RBlock, kind: Literal["furniture", "toc"], reason: str) -> SetAside:
    region = block.regions[0] if block.regions else None
    return SetAside(
        block=block.id,
        kind=kind,
        text=block.text,
        page=region.page if region else 1,
        bbox=region.bbox if region else (0.0, 0.0, 0.0, 0.0),
        reason=reason,
    )


def _runs(blocks: Sequence[RBlock]) -> list[tuple[int, int]]:
    """Maximal runs `[start, end)` of consecutive TOC lines."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, block in enumerate(blocks):
        if is_toc_line(block) or (start is not None and is_toc_heading(block)):
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(blocks)))
    return runs


def _heading_before(blocks: Sequence[RBlock], start: int) -> int | None:
    """The index of a TOC heading within three blocks before `start`, nearest first."""
    for i in range(start - 1, max(start - 1 - _HEADING_REACH, -1), -1):
        if is_toc_heading(blocks[i]):
            return i
    return None


def _body_page(blocks: Sequence[RBlock]) -> int | None:
    """The first page holding a paragraph of more than 40 words."""
    for block in blocks:
        if block.kind == "paragraph" and len(block.text.split()) > _BODY_WORDS:
            return block.page
    return None


def _kept(blocks: Sequence[RBlock], start: int, end: int, body_page: int | None) -> bool:
    """Keep-guard: a numbered body list whose numbers are later heading numbers is content."""
    if body_page is None or blocks[start].page < body_page:
        return False
    later = {
        b.number.rstrip(".") for b in blocks[end:] if b.kind == "heading" and b.number is not None
    }
    hits = sum(1 for b in blocks[start:end] if page_reference(b.text) in later)
    return 2 * hits > end - start


def _toc_blocks(blocks: Sequence[RBlock]) -> set[str]:
    body_page = _body_page(blocks)
    out: set[str] = set()
    for start, end in _runs(blocks):
        heading = _heading_before(blocks, start)
        needed = _RUN_MIN if heading is None else _RUN_MIN_AFTER_HEADING
        if end - start < needed or (heading is None and _kept(blocks, start, end, body_page)):
            continue
        out.update(b.id for b in blocks[start:end])
        if heading is not None and heading == start - 1:
            out.add(blocks[heading].id)
    return out


def set_aside(blocks: Sequence[RBlock]) -> list[SetAside]:
    """Set-aside entries for the reading's blocks, in reading order."""
    content = [b for b in blocks if b.kind != "furniture"]
    toc = _toc_blocks(content)
    entries: list[SetAside] = []
    for block in blocks:
        if block.kind == "furniture":
            entries.append(_entry(block, "furniture", FURNITURE))
        elif block.id in toc:
            entries.append(_entry(block, "toc", TOC))
    return entries
