"""Types the structure stage hands to later stages."""

from __future__ import annotations

from dataclasses import dataclass, field

from inkthread.domain.model import Bbox


@dataclass(frozen=True)
class GeomWord:
    """One content word on a page: the node it belongs to and its span in that node's text."""

    node: str | None
    start: int | None
    end: int | None
    bbox: Bbox


@dataclass
class SectionIndex:
    """Sections by printed key, for reference resolution (spec 04 § 5).

    `by_key` maps (counter, number) to a section node id. Counters: `num` for numbered headings,
    otherwise the lower-cased keyword (`part`, `chapter`, `title`, `book`, `appendix`, `article`,
    `section`); annex, schedule, exhibit and attachment index under `appendix`.
    """

    by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    numbers: dict[str, str] = field(default_factory=dict)  # node id -> printed number

    def find(self, counter: str, number: str) -> str | None:
        """Resolve by the counter first, then as a bare number."""
        return self.by_key.get((counter, number)) or self.by_key.get(("num", number))


@dataclass
class StructureResult:
    """What `build_structure` returns beside the filled draft."""

    sections: SectionIndex
    title_node: str | None
    block_to_node: dict[str, str]
    geometry: dict[int, list[GeomWord]]
