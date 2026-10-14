"""Flags from inkgrid (spec 02 § 8): hidden text and verifier defects."""

from __future__ import annotations

from collections.abc import Mapping

from inkthread.domain.draft import GraphDraft
from inkthread.domain.model import Actor, Flag, FlagCode, Maker, Span
from inkthread.domain.reading import Reading
from inkthread.domain.structure.placement import BlockPlace

FLAGS = "R-INK-flags"
FLAG_MAKER = Maker(actor=Actor.RULE, id=FLAGS)


def add_hidden(
    draft: GraphDraft, reading: Reading, places: Mapping[str, BlockPlace], *, stage: str
) -> None:
    """Flag `hidden_text` with the count of hidden words, and list their spans."""
    counts: dict[str, int] = {}
    for block in reading.blocks:
        place = places.get(block.id)
        if place is None:
            continue
        node = draft.node(place.node)
        for word in block.words:
            if not word.hidden:
                continue
            counts[place.node] = counts.get(place.node, 0) + 1
            if word.start is None or word.end is None or place.offset is None:
                continue
            start, end = place.offset + word.start, place.offset + word.end
            if 0 <= start < end <= len(node.text):
                node.hidden_spans.append(Span.of(node.text, start, end))
    for node_id, count in counts.items():
        flag = Flag(code=FlagCode.HIDDEN_TEXT, detail=str(count))
        draft.add_flag(node_id, flag, stage=stage, maker=FLAG_MAKER)


def add_defects(
    draft: GraphDraft, reading: Reading, places: Mapping[str, BlockPlace], *, stage: str
) -> None:
    """Flag `text_defect` (detail = the code) on the node of every block with a defect."""
    for defect in reading.defects:
        place = places.get(defect.block) if defect.block is not None else None
        if place is None:
            continue
        flag = Flag(code=FlagCode.TEXT_DEFECT, detail=defect.code)
        draft.add_flag(place.node, flag, stage=stage, maker=FLAG_MAKER)
