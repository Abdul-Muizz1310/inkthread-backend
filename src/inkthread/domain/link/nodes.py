"""Shared helpers for the link stage: which nodes it reads and how it adds its own."""

from __future__ import annotations

from inkthread.domain.draft import GraphDraft, NodeDraft
from inkthread.domain.model import Actor, Maker, NodeKind

STAGE = "link_rules"

CONTENT_KINDS = (
    NodeKind.PARAGRAPH,
    NodeKind.LIST_ITEM,
    NodeKind.NOTE,
    NodeKind.DEFINITION,
    NodeKind.TABLE,
)


def rule(rule_id: str) -> Maker:
    """The maker for a rule-made element."""
    return Maker(actor=Actor.RULE, id=rule_id)


def content_nodes(draft: GraphDraft) -> list[NodeDraft]:
    """The parts a resolver scans, in reading order."""
    return draft.nodes_of(*CONTENT_KINDS)


def next_order(draft: GraphDraft) -> int:
    """The first reading-order slot after every existing node."""
    return max((n.order for n in draft.nodes.values()), default=0) + 1


def add_unplaced(draft: GraphDraft, node_id: str, kind: NodeKind, text: str, maker: Maker) -> bool:
    """Add a term or external node after every other node; False when it already exists."""
    if node_id in draft.nodes:
        return False
    draft.add_node(
        NodeDraft(
            id=node_id,
            kind=kind,
            text=text,
            order=next_order(draft),
            section=None,
            depth=0,
            regions=[],
            made_by=maker,
        ),
        stage=STAGE,
    )
    return True
