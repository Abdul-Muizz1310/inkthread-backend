"""Heading merge (spec 02 § 4), heading keys and the section tree (§ 5)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from inkthread.domain.reading import RBlock

MERGE = "R-SEC-merge"
CONTAINS = "R-SEC-contains"

_MERGE_GAP = 0.8
_MERGE_LIMIT = 200
_NO_LEVEL = 1_000_000  # a heading inkgrid gave no level reads as the smallest type

_RANK0 = (
    "part",
    "chapter",
    "title",
    "book",
    "appendix",
    "annex",
    "schedule",
    "exhibit",
    "attachment",
)
_RANKS = {**dict.fromkeys(_RANK0, 0), "article": 1, "section": 2, "§": 2}
_COUNTERS = {"annex": "appendix", "schedule": "appendix", "exhibit": "appendix"}
_COUNTERS |= {"attachment": "appendix", "§": "section"}
_KEYWORD = re.compile(
    r"^\s*(?:(?P<word>" + "|".join([*_RANK0, "article", "section"]) + r")\s+|(?P<sign>§)\s*)"
    r"(?P<num>\d+(?:\.\d+)*|[ivxlcdm]+|[a-z])(?![\w])",
    re.IGNORECASE,
)


class KeyKind(StrEnum):
    """How a heading is keyed."""

    KEYWORD = "keyword"
    NUMBERED = "numbered"
    PLAIN = "plain"


@dataclass(frozen=True)
class HeadingKey:
    """A heading's key: its kind, rank, index counter and printed number."""

    kind: KeyKind
    rank: int = 0
    counter: str | None = None
    number: str | None = None

    @property
    def parts(self) -> tuple[str, ...]:
        """The dotted parts of a numbered heading's number."""
        return tuple(p for p in (self.number or "").split(".") if p)


def heading_key(block: RBlock) -> HeadingKey:
    """Keyword first, then inkgrid's number, else plain."""
    match = _KEYWORD.match(block.text)
    if match is not None:
        word = (match.group("word") or match.group("sign")).lower()
        return HeadingKey(
            kind=KeyKind.KEYWORD,
            rank=_RANKS[word],
            counter=_COUNTERS.get(word, word),
            number=match.group("num"),
        )
    if block.number is not None and block.number.strip(". "):
        number = block.number.strip().rstrip(".")
        rank = 2 + len([p for p in number.split(".") if p])
        return HeadingKey(kind=KeyKind.NUMBERED, rank=rank, counter="num", number=number)
    return HeadingKey(kind=KeyKind.PLAIN)


@dataclass(frozen=True)
class HeadingGroup:
    """One section's heading: one block, or several merged by `R-SEC-merge`."""

    blocks: tuple[RBlock, ...]
    key: HeadingKey

    @property
    def text(self) -> str:
        """The heading texts joined by a newline."""
        return "\n".join(b.text for b in self.blocks)

    @property
    def merged(self) -> bool:
        """Whether more than one block made this heading."""
        return len(self.blocks) > 1

    @property
    def level(self) -> int:
        """The first block's level (smaller is larger type)."""
        level = self.blocks[0].level
        return _NO_LEVEL if level is None else level


Item = HeadingGroup | RBlock


def _can_merge(group: HeadingGroup, nxt: RBlock) -> bool:
    prev = group.blocks[-1]
    if not prev.regions or not nxt.regions:
        return False
    if prev.page != nxt.page or prev.level != nxt.level:
        return False
    if nxt.number is not None or heading_key(nxt).kind is KeyKind.KEYWORD:
        return False
    top = prev.regions[0].bbox
    gap = nxt.regions[0].bbox[1] - prev.regions[-1].bbox[3]
    if gap > _MERGE_GAP * (top[3] - top[1]):
        return False
    return len(group.text) + 1 + len(nxt.text) <= _MERGE_LIMIT


def merge_headings(blocks: Sequence[RBlock], exclude: frozenset[str] = frozenset()) -> list[Item]:
    """Group consecutive mergeable headings. Blocks in `exclude` (the title and its repeats) pass
    through unchanged and never merge."""
    items: list[Item] = []
    for block in blocks:
        last = items[-1] if items else None
        if block.kind != "heading" or block.id in exclude:
            items.append(block)
        elif isinstance(last, HeadingGroup) and _can_merge(last, block):
            items[-1] = HeadingGroup(blocks=(*last.blocks, block), key=last.key)
        else:
            items.append(HeadingGroup(blocks=(block,), key=heading_key(block)))
    return items


def _proper_prefix(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    return len(a) < len(b) and b[: len(a)] == a


def closes(top: HeadingGroup, head: HeadingGroup, *, top_has_content: bool) -> bool:
    """Whether heading `head` closes the open section `top` (spec 02 § 5's table)."""
    t, h = top.key.kind, head.key.kind
    match (t, h):
        case (KeyKind.NUMBERED, KeyKind.NUMBERED):
            return not _proper_prefix(top.key.parts, head.key.parts)
        case (KeyKind.PLAIN, KeyKind.PLAIN):
            if top.level == head.level:
                return top_has_content
            return top.level > head.level
        case (KeyKind.PLAIN, _) | (_, KeyKind.PLAIN):
            return top.level >= head.level
        case _:
            return top.key.rank >= head.key.rank


@dataclass(frozen=True)
class Placed:
    """An item and the heading group it sits under (None: the document)."""

    item: Item
    parent: HeadingGroup | None


@dataclass
class _Open:
    group: HeadingGroup
    has_content: bool = False  # directly holds a non-heading block


def build_tree(items: Sequence[Item]) -> list[Placed]:
    """Walk the items with a stack of open sections; every item gets its parent."""
    stack: list[_Open] = []
    placed: list[Placed] = []
    for item in items:
        if isinstance(item, HeadingGroup):
            while stack and closes(stack[-1].group, item, top_has_content=stack[-1].has_content):
                stack.pop()
            placed.append(Placed(item=item, parent=stack[-1].group if stack else None))
            stack.append(_Open(group=item))
        else:
            if stack:
                stack[-1].has_content = True
            placed.append(Placed(item=item, parent=stack[-1].group if stack else None))
    return placed


def index_key(key: HeadingKey) -> tuple[str, str] | None:
    """The section index key `(counter, number)` of a keyed heading."""
    if key.counter is None or key.number is None:
        return None
    return key.counter, key.number
