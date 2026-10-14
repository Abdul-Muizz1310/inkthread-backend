"""The structure stage (spec 02): from a Reading to the skeleton graph draft."""

from __future__ import annotations

from dataclasses import dataclass, field

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.ids import TwinRegistry, document_id, part_id, section_id
from inkthread.domain.model import (
    Actor,
    Basis,
    EdgeType,
    Finding,
    Flag,
    FlagCode,
    Maker,
    NodeKind,
    Region,
)
from inkthread.domain.reading import RBlock, Reading
from inkthread.domain.structure.flags import FLAG_MAKER, add_defects, add_hidden
from inkthread.domain.structure.geometry import build_geometry
from inkthread.domain.structure.inklinks import add_continues, add_note_calls
from inkthread.domain.structure.parts import INKGRID, make_part, part_kind
from inkthread.domain.structure.placement import BlockPlace
from inkthread.domain.structure.sections import (
    CONTAINS,
    MERGE,
    HeadingGroup,
    build_tree,
    index_key,
    merge_headings,
)
from inkthread.domain.structure.setaside import set_aside
from inkthread.domain.structure.title import TITLE, TitleResult, find_title
from inkthread.domain.structure.types import SectionIndex, StructureResult

STAGE = "structure"
CONTAINS_MAKER = Maker(actor=Actor.RULE, id=CONTAINS)
MERGE_MAKER = Maker(actor=Actor.RULE, id=MERGE)
TITLE_MAKER = Maker(actor=Actor.RULE, id=TITLE)


@dataclass
class _Frame:
    """An open container: its node id, depth and the section titles from the root to it."""

    node: str
    depth: int
    titles: tuple[str, ...] = ()


@dataclass
class _Builder:
    reading: Reading
    draft: GraphDraft
    order: dict[str, int] = field(default_factory=dict)
    places: dict[str, BlockPlace] = field(default_factory=dict)
    twins: TwinRegistry = field(default_factory=TwinRegistry)
    index: SectionIndex = field(default_factory=SectionIndex)
    frames: dict[str, _Frame] = field(default_factory=dict)  # first heading block id -> frame

    def __post_init__(self) -> None:
        self.order = {b.id: i + 1 for i, b in enumerate(self.reading.blocks)}

    def set_aside(self) -> set[str]:
        aside: set[str] = set()
        for entry in set_aside(self.reading.blocks):
            maker = Maker(actor=Actor.RULE, id=entry.reason)
            self.draft.set_aside_block(entry, stage=STAGE, maker=maker)
            aside.add(entry.block)
        return aside

    def document(self, title: TitleResult) -> _Frame:
        text = title.text
        label = " ".join(text.split()) or self.reading.file_name or "document"
        cited = [*title.lines, *title.repeats]
        node = NodeDraft(
            id=document_id(self.reading.sha256),
            kind=NodeKind.DOCUMENT,
            text=text,
            order=0,
            section=None,
            depth=0,
            regions=[Region(page=r.page, bbox=r.bbox) for b in title.lines for r in b.regions],
            made_by=TITLE_MAKER,
            label=label,
            source_blocks=[b.id for b in cited],
            source_keys=[b.key for b in cited],
        )
        self.draft.add_node(node, stage=STAGE)
        offset = 0
        for b in title.lines:
            self.places[b.id] = BlockPlace(node=node.id, offset=offset)
            offset += len(b.text) + 1
        for b in title.repeats:
            self.places[b.id] = BlockPlace(node=node.id, offset=None)
        return _Frame(node=node.id, depth=0)

    def contain(self, parent: str, child: str) -> None:
        edge = EdgeDraft(
            type=EdgeType.CONTAINS,
            source=parent,
            target=child,
            basis=Basis.EXPLICIT,
            method=CONTAINS,
            made_by=CONTAINS_MAKER,
        )
        self.draft.add_edge(edge, stage=STAGE)

    def section(self, group: HeadingGroup, parent: _Frame) -> None:
        text = group.text
        node_id = self.twins.claim(section_id(parent.titles, text))
        node = NodeDraft(
            id=node_id,
            kind=NodeKind.SECTION,
            text=text,
            order=self.order[group.blocks[0].id],
            section=parent.node,
            depth=parent.depth + 1,
            regions=[Region(page=r.page, bbox=r.bbox) for b in group.blocks for r in b.regions],
            made_by=MERGE_MAKER if group.merged else INKGRID,
            source_blocks=[b.id for b in group.blocks],
            source_keys=[b.key for b in group.blocks],
        )
        self.draft.add_node(node, stage=STAGE)
        self.contain(parent.node, node_id)
        if group.merged:
            self.draft.add_flag(node_id, Flag(code=FlagCode.MERGED_HEADING), stage=STAGE)
        offset = 0
        for b in group.blocks:
            self.places[b.id] = BlockPlace(node=node_id, offset=offset)
            offset += len(b.text) + 1
        key = index_key(group.key)
        if key is not None:
            self.index.by_key.setdefault(key, node_id)
            self.index.numbers[node_id] = key[1]
        frame = _Frame(node=node_id, depth=parent.depth + 1, titles=(*parent.titles, text))
        self.frames[group.blocks[0].id] = frame

    def part(self, block: RBlock, parent: _Frame) -> None:
        kind = part_kind(block.kind)
        if kind is None:
            msg = f"block {block.id} of kind {block.kind} cannot become a part"
            raise ValueError(msg)
        node_id = self.twins.claim(part_id(kind.value, parent.titles, block.text))
        node = make_part(
            block,
            node_id=node_id,
            kind=kind,
            order=self.order[block.id],
            section=parent.node,
            depth=parent.depth + 1,
        )
        self.draft.add_node(node, stage=STAGE)
        self.contain(parent.node, node_id)
        if node.table is not None and node.table.header_rows == 0:
            flag = Flag(code=FlagCode.HEADER_NOT_FOUND)
            self.draft.add_flag(node_id, flag, stage=STAGE, maker=FLAG_MAKER)
        self.places[block.id] = BlockPlace(node=node_id, offset=0)

    def tree(self, content: list[RBlock], title: TitleResult, root: _Frame) -> None:
        exclude = frozenset(title.block_ids)
        items = [
            i
            for i in merge_headings(content, exclude)
            if isinstance(i, HeadingGroup) or i.id not in exclude
        ]
        for placed in build_tree(items):
            parent = root if placed.parent is None else self.frames[placed.parent.blocks[0].id]
            if isinstance(placed.item, HeadingGroup):
                self.section(placed.item, parent)
            else:
                self.part(placed.item, parent)


def build_structure(reading: Reading, draft: GraphDraft) -> StructureResult:
    """Fill the draft with the structure stage's output and return what later stages need."""
    builder = _Builder(reading=reading, draft=draft)
    aside = builder.set_aside()
    content = [b for b in reading.blocks if b.id not in aside]
    title = find_title(content)
    root = builder.document(title)
    builder.tree(content, title, root)
    places = builder.places
    add_hidden(draft, reading, places, stage=STAGE)
    add_defects(draft, reading, places, stage=STAGE)
    add_continues(draft, reading, places, stage=STAGE)
    add_note_calls(draft, reading, places, stage=STAGE)
    draft.findings.extend(
        Finding(code=f.code, severity=f.severity, page=f.page, detail=f.detail)
        for f in reading.findings
    )
    return StructureResult(
        sections=builder.index,
        title_node=root.node if title.block is not None else None,
        block_to_node={bid: p.node for bid, p in places.items()},
        geometry=build_geometry(reading, places),
    )
