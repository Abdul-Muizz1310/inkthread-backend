"""Content blocks become part nodes (spec 02 § 6)."""

from __future__ import annotations

from inkthread.domain.draft import NodeDraft
from inkthread.domain.model import Actor, Maker, NodeKind, Region
from inkthread.domain.reading import BlockKind, RBlock
from inkthread.domain.structure.tables import table_info

INKGRID = Maker(actor=Actor.INKGRID, id="inkgrid")


def part_kind(kind: BlockKind) -> NodeKind | None:
    """The node kind of a content block; None for headings and furniture, which make no part."""
    match kind:
        case "paragraph":
            return NodeKind.PARAGRAPH
        case "list_item":
            return NodeKind.LIST_ITEM
        case "footnote":
            return NodeKind.NOTE
        case "definition":
            return NodeKind.DEFINITION
        case "table":
            return NodeKind.TABLE
        case "heading" | "furniture":
            return None


def make_part(
    block: RBlock, *, node_id: str, kind: NodeKind, order: int, section: str, depth: int
) -> NodeDraft:
    """The part node for one content block."""
    table = None
    if kind is NodeKind.TABLE:
        if block.grid is None:
            msg = f"table block {block.id} has no grid"
            raise ValueError(msg)
        table = table_info(block.grid)
    marker = block.label if kind in {NodeKind.LIST_ITEM, NodeKind.NOTE} else None
    return NodeDraft(
        id=node_id,
        kind=kind,
        text=block.text,
        order=order,
        section=section,
        depth=depth,
        regions=[Region(page=r.page, bbox=r.bbox) for r in block.regions],
        made_by=INKGRID,
        table=table,
        marker=marker,
        source_blocks=[block.id],
        source_keys=[block.key],
    )
