"""Per-page word geometry for the viewer (spec 02 § 9)."""

from __future__ import annotations

from collections.abc import Mapping

from inkthread.domain.reading import Reading
from inkthread.domain.structure.placement import BlockPlace
from inkthread.domain.structure.types import GeomWord


def build_geometry(reading: Reading, places: Mapping[str, BlockPlace]) -> dict[int, list[GeomWord]]:
    """Every aligned word, by page: content words carry their node and their offsets in its text;
    set-aside words carry no node and their offsets in their own block's text."""
    pages: dict[int, list[GeomWord]] = {p.number: [] for p in reading.pages}
    for block in reading.blocks:
        place = places.get(block.id)
        for word in block.words:
            if word.start is None or word.end is None:
                continue
            if place is None:
                geom = GeomWord(node=None, start=word.start, end=word.end, bbox=word.bbox)
            elif place.offset is None:
                geom = GeomWord(node=place.node, start=None, end=None, bbox=word.bbox)
            else:
                start, end = place.offset + word.start, place.offset + word.end
                geom = GeomWord(node=place.node, start=start, end=end, bbox=word.bbox)
            pages.setdefault(word.page, []).append(geom)
    return pages
