"""Lead-ins that govern the table or list after them (spec 04 § 8)."""

from __future__ import annotations

import re

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.link.nodes import STAGE, content_nodes, rule
from inkthread.domain.model import Basis, EdgeType, NodeKind, Span
from inkthread.domain.text import sentences

RULE = "R-GOV-leadin"

_LEADIN_END = re.compile(r"(?:\bas\s+follows:?|\bthe\s+following:|:)\s*\Z", re.IGNORECASE)
_LEADIN_KINDS = frozenset({NodeKind.PARAGRAPH, NodeKind.LIST_ITEM})


def _governed(parts: list[NodeDraft], at: int) -> list[NodeDraft]:
    if at + 1 >= len(parts):
        return []
    lead, first = parts[at], parts[at + 1]
    if first.section != lead.section:
        return []
    if first.kind is NodeKind.TABLE:
        return [first]
    run: list[NodeDraft] = []
    for node in parts[at + 1 :]:
        if node.kind is not NodeKind.LIST_ITEM or node.section != lead.section:
            break
        run.append(node)
    return run


def _last_sentence(text: str) -> Span:
    start, end = sentences(text)[-1]
    while end > start and text[end - 1].isspace():
        end -= 1
    return Span.of(text, start, end)


def link_leadins(draft: GraphDraft) -> None:
    """Add `governs` from each lead-in to the table or list-item run right after it."""
    parts = content_nodes(draft)
    for i, node in enumerate(parts):
        if node.kind not in _LEADIN_KINDS or _LEADIN_END.search(node.text) is None:
            continue
        evidence = _last_sentence(node.text)
        for target in _governed(parts, i):
            draft.add_edge(
                EdgeDraft(
                    type=EdgeType.GOVERNS,
                    source=node.id,
                    target=target.id,
                    basis=Basis.EXPLICIT,
                    method=RULE,
                    made_by=rule(RULE),
                    evidence=evidence,
                ),
                stage=STAGE,
            )
