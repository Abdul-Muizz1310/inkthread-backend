"""Edges from inkgrid's links (spec 02 § 7): `continues` and `cites_note`."""

from __future__ import annotations

import re
from collections.abc import Mapping

from inkthread.domain.draft import EdgeDraft, GraphDraft
from inkthread.domain.model import (
    Actor,
    Anchor,
    Basis,
    EdgeType,
    Flag,
    FlagCode,
    Maker,
    NodeKind,
    Span,
    Unresolved,
)
from inkthread.domain.reading import RBlock, Reading, RLink
from inkthread.domain.structure.flags import FLAG_MAKER
from inkthread.domain.structure.placement import BlockPlace

CONTINUES = "R-INK-continues"
NOTE = "R-INK-note"
CONTINUES_MAKER = Maker(actor=Actor.INKGRID, id=CONTINUES)
NOTE_MAKER = Maker(actor=Actor.INKGRID, id=NOTE)


def _block_span(block: RBlock, link: RLink) -> tuple[int, int] | None:
    """The call marker's offsets in the caller block's text, or None."""
    label = link.label
    if not label:
        return None
    match link.method:
        case "superscript":
            for word in block.words:
                if (
                    word.superscript
                    and word.start is not None
                    and word.end is not None
                    and block.text[word.start : word.end] == label
                ):
                    return word.start, word.end
            return None
        case "parenthetical":
            at = block.text.find(f"({label})")
            return None if at < 0 else (at, at + len(label) + 2)
        case "named":
            pattern = rf"(?<![\w])(?:foot)?note\s+{re.escape(label)}(?![\w])"
            found = re.search(pattern, block.text, re.IGNORECASE)
            return None if found is None else (found.start(), found.end())
        case None:
            return None


def call_evidence(block: RBlock, link: RLink, place: BlockPlace, text: str) -> Span | None:
    """The evidence span of a footnote call in its caller node's text."""
    span = _block_span(block, link)
    if span is None or place.offset is None:
        return None
    start, end = place.offset + span[0], place.offset + span[1]
    if not 0 <= start < end <= len(text):
        return None
    return Span.of(text, start, end)


def add_continues(
    draft: GraphDraft, reading: Reading, places: Mapping[str, BlockPlace], *, stage: str
) -> None:
    """One `continues` edge, child to parent, per resolved continuation link."""
    for link in reading.links:
        if link.kind != "continuation" or link.status != "resolved" or link.to_block is None:
            continue
        child, parent = places.get(link.from_block), places.get(link.to_block)
        if child is None or parent is None or child.node == parent.node:
            continue
        edge = EdgeDraft(
            type=EdgeType.CONTINUES,
            source=child.node,
            target=parent.node,
            basis=Basis.EXPLICIT,
            method=CONTINUES,
            made_by=CONTINUES_MAKER,
        )
        draft.add_edge(edge, stage=stage)


def _unresolved(
    draft: GraphDraft, node_id: str, link: RLink, span: Span | None, stage: str
) -> None:
    label = link.label or ""
    flag = Flag(code=FlagCode.NOTE_NOT_FOUND, detail=label or None)
    draft.add_flag(node_id, flag, stage=stage, maker=FLAG_MAKER)
    entry = Unresolved(kind="note", text=label, span=span, reason="note_not_found")
    draft.add_unresolved(node_id, entry, stage=stage, maker=FLAG_MAKER)


def add_note_calls(
    draft: GraphDraft, reading: Reading, places: Mapping[str, BlockPlace], *, stage: str
) -> None:
    """`cites_note` for resolved calls; `note_not_found` for unresolved ones; rejected and
    set-aside callers are ignored."""
    for link in reading.links:
        if link.kind != "footnote_call" or link.status == "rejected":
            continue
        caller = places.get(link.from_block)
        if caller is None:
            continue
        node = draft.node(caller.node)
        span = call_evidence(reading.block(link.from_block), link, caller, node.text)
        target = places.get(link.to_block) if link.to_block is not None else None
        resolved = link.status == "resolved" and target is not None
        if not resolved or target is None or draft.node(target.node).kind is not NodeKind.NOTE:
            _unresolved(draft, caller.node, link, span, stage)
            continue
        if target.node == caller.node:
            continue
        anchor = None
        if link.from_cell is not None and node.table is not None:
            anchor = Anchor(row=link.from_cell[0], col=link.from_cell[1])
        edge = EdgeDraft(
            type=EdgeType.CITES_NOTE,
            source=caller.node,
            target=target.node,
            basis=Basis.EXPLICIT,
            method=NOTE,
            made_by=NOTE_MAKER,
            evidence=span,
            anchor=anchor,
            label=link.label,
        )
        draft.add_edge(edge, stage=stage)
