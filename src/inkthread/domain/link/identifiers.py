"""Identifiers printed in a table's key column, referred to from elsewhere (spec 04 § 6)."""

from __future__ import annotations

import re

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.link.nodes import STAGE, content_nodes, rule
from inkthread.domain.model import Anchor, Basis, CellInfo, EdgeType, NodeKind, Span, TableInfo

RULE = "R-REF-identifier"

_KEY_HEADER = re.compile(
    r"code|(?<!\w)id(?!\w)|no\.|number|§|rule|section|article|clause|ref", re.IGNORECASE
)
_MONEY = re.compile(
    r"^[-+(]?(?:[$€£¥]|[A-Z]{3}\s?)?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?$"
    r"|^[-+(]?[$€£¥]"
    r"|%$"
    r"|^0\.\d+$"
)
_DIGIT = re.compile(r"\d")
_SHAPE = re.compile(r"[A-Za-z.\-/(]")
_MAX_LEN = 20
_KEY_SHARE = 0.6
_KEY_COLUMNS = 2


def is_identifier(text: str) -> bool:
    """A short token with a digit and a letter or `.`/`-`/`/`/`(`; not money, not a bare integer."""
    value = text.strip()
    return (
        0 < len(value) <= _MAX_LEN
        and not any(ch.isspace() for ch in value)
        and _DIGIT.search(value) is not None
        and _SHAPE.search(value) is not None
        and _MONEY.search(value) is None
    )


def _body(table: TableInfo) -> list[CellInfo]:
    return [
        c
        for c in table.cells
        if not c.is_header and c.row >= table.header_rows and c.row not in table.banner_rows
    ]


def key_identifiers(table: TableInfo) -> set[str]:
    """The identifiers in this table's key columns."""
    body = _body(table)
    found: set[str] = set()
    for col in range(table.n_cols):
        header = " ".join(c.text for c in table.cells if c.col == col and c not in body)
        if col >= _KEY_COLUMNS and _KEY_HEADER.search(header) is None:
            continue
        cells = [c.text.strip() for c in body if c.col == col and c.text.strip()]
        ids = [v for v in cells if is_identifier(v)]
        if cells and len(ids) / len(cells) >= _KEY_SHARE:
            found.update(ids)
    return found


def cell_spans(node: NodeDraft) -> list[tuple[int, int, CellInfo]]:
    """Where each cell's text sits in the table node's text, found in reading order."""
    if node.table is None:
        return []
    spans: list[tuple[int, int, CellInfo]] = []
    pos = 0
    for cell in sorted(node.table.cells, key=lambda c: (c.row, c.col)):
        if not cell.text:
            continue
        at = node.text.find(cell.text, pos)
        if at < 0:
            continue
        spans.append((at, at + len(cell.text), cell))
        pos = at + len(cell.text)
    return spans


def _anchor(node: NodeDraft, start: int) -> Anchor | None:
    for s, e, cell in cell_spans(node):
        if s <= start < e:
            return Anchor(row=cell.row, col=cell.col)
    return None


def link_identifiers(draft: GraphDraft) -> None:
    """Add `refers_to` from every part that prints a key-column identifier to its table."""
    owner: dict[str, str] = {}
    for table in draft.nodes_of(NodeKind.TABLE):
        if table.table is None:
            continue
        for ident in sorted(key_identifiers(table.table)):
            owner.setdefault(ident, table.id)
    if not owner:
        return
    alternatives = "|".join(re.escape(i) for i in sorted(owner, key=lambda i: (-len(i), i)))
    pattern = re.compile(rf"(?<![\w.\-/])(?:{alternatives})(?![\w\-/(]|\.\w)")
    for node in content_nodes(draft):
        for m in pattern.finditer(node.text):
            target = owner[m.group()]
            if target == node.id:
                continue
            anchor = _anchor(node, m.start()) if node.kind is NodeKind.TABLE else None
            draft.add_edge(
                EdgeDraft(
                    type=EdgeType.REFERS_TO,
                    source=node.id,
                    target=target,
                    basis=Basis.EXPLICIT,
                    method=RULE,
                    made_by=rule(RULE),
                    evidence=Span.of(node.text, m.start(), m.end()),
                    anchor=anchor,
                    label=m.group(),
                ),
                stage=STAGE,
            )
