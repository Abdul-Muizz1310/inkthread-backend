"""The residual the classify agent receives (spec 03 § 4)."""

from __future__ import annotations

from inkthread.domain.draft import GraphDraft, NodeDraft
from inkthread.domain.model import NodeKind

MIN_VISIBLE = 40


def visible_text(node: NodeDraft) -> str:
    """The node's text with its hidden spans removed."""
    hidden = sorted((s.start, s.end) for s in node.hidden_spans)
    kept: list[str] = []
    pos = 0
    for start, end in hidden:
        if start > pos:
            kept.append(node.text[pos:start])
        pos = max(pos, end)
    kept.append(node.text[pos:])
    return "".join(kept)


def residual(draft: GraphDraft) -> list[str]:
    """Untyped paragraphs, list items and notes with 40+ visible characters, in reading order."""
    return [
        n.id
        for n in draft.nodes_of(NodeKind.PARAGRAPH, NodeKind.LIST_ITEM, NodeKind.NOTE)
        if not n.roles and len(visible_text(n).strip()) >= MIN_VISIBLE
    ]
