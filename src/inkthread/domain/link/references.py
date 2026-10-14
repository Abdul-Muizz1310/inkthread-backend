"""Internal references: sections, captions and positions (spec 04 § 5).

`link_references` resolves every reference and records the misses; `emit_references` turns the
resolved ones into `refers_to` edges, minus those a precedence rule consumed (spec 04 § 7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.link.citations import find_citations, qualified_refs
from inkthread.domain.link.nodes import CONTENT_KINDS, STAGE, content_nodes, rule
from inkthread.domain.link.refsyntax import (
    REF_LIST,
    PrintedRef,
    after_this,
    counter_of,
    split_refs,
)
from inkthread.domain.model import Basis, EdgeType, Flag, FlagCode, NodeKind, Span, Unresolved
from inkthread.domain.structure.types import SectionIndex

SECTION_RULE = "R-REF-section"
CAPTION_RULE = "R-REF-caption"
POSITIONAL_RULE = "R-REF-positional"

_CAPTION = re.compile(
    r"(?<!\w)(?P<word>Table|Figure|Fig\.|Exhibit|Chart)\s+"
    r"(?P<num>(?:[A-Z]-?)?\d+(?:[.-]\d+)*[a-z]?|[A-Z])(?!\w)"
)
_POSITIONAL = re.compile(
    r"(?<!\w)the\s+(?:(?P<dir1>following|preceding|above|below)\s+"
    r"(?P<what1>table|schedule|list|chart|figure)s?"
    r"|(?P<what2>table|schedule|list|chart|figure)s?\s+(?P<dir2>below|above))(?!\w)",
    re.IGNORECASE,
)
_FORWARD = frozenset({"following", "below"})
_REACH = 4
_CAPTION_REACH = 2


@dataclass(frozen=True)
class ResolvedRef:
    """A reference from one node to the node it names."""

    node: str
    target: str
    span: Span
    label: str
    rule: str
    weak: bool = False


def _caption_key(m: re.Match[str]) -> tuple[str, str]:
    word = m.group("word").lower().rstrip(".")
    return ("figure" if word == "fig" else word), m.group("num")


def _caption_index(draft: GraphDraft) -> dict[tuple[str, str], tuple[str, str]]:
    """(word, number) → (caption node, target node)."""
    ordered = draft.nodes_of(NodeKind.SECTION, *CONTENT_KINDS)
    parts = [n for n in ordered if n.kind is not NodeKind.SECTION]
    index: dict[tuple[str, str], tuple[str, str]] = {}
    for node in ordered:
        if node.kind not in {NodeKind.SECTION, NodeKind.PARAGRAPH}:
            continue
        m = _CAPTION.match(node.text.lstrip())
        if m is None:
            continue
        after = [p for p in parts if p.order > node.order][:_CAPTION_REACH]
        table = next((p for p in after if p.kind is NodeKind.TABLE), None)
        index.setdefault(_caption_key(m), (node.id, table.id if table else node.id))
    return index


def _unresolved(draft: GraphDraft, node: NodeDraft, span: Span, method: str, why: str) -> None:
    maker = rule(method)
    draft.add_flag(node.id, Flag(code=FlagCode.REFERENCE_UNRESOLVED), stage=STAGE, maker=maker)
    entry = Unresolved(kind="reference", text=span.quote, span=span, reason=why)
    draft.add_unresolved(node.id, entry, stage=STAGE, maker=maker)


def _caption_refs(
    draft: GraphDraft,
    node: NodeDraft,
    index: dict[tuple[str, str], tuple[str, str]],
    claimed: list[tuple[int, int]],
) -> list[ResolvedRef]:
    refs: list[ResolvedRef] = []
    for m in _CAPTION.finditer(node.text):
        key = _caption_key(m)
        span = Span.of(node.text, m.start(), m.end())
        found = index.get(key)
        if found is None:
            if key[0] != "exhibit":
                _unresolved(draft, node, span, CAPTION_RULE, "no caption carries this number")
            continue
        claimed.append((m.start(), m.end()))
        caption, target = found
        if target == node.id or (caption == node.id and not node.text[: m.start()].strip()):
            continue
        refs.append(ResolvedRef(node.id, target, span, span.quote, CAPTION_RULE))
    return refs


def _resolve(sections: SectionIndex, counter: str, ref: str) -> str | None:
    target = sections.find(counter, ref)
    base = ref
    while target is None and "(" in base:
        base = base[: base.rfind("(")]
        target = sections.find(counter, base)
    return target


def _number_key(number: str) -> tuple[int, ...] | None:
    parts = number.split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def _between(sections: SectionIndex, lo: str, hi: str) -> list[str]:
    low, high = _number_key(lo), _number_key(hi)
    if low is None or high is None or len(low) != len(high):
        return []
    inside = []
    for number in set(sections.numbers.values()):
        key = _number_key(number)
        if key is not None and len(key) == len(low) and low < key < high:
            inside.append(number)
    return sorted(inside, key=lambda n: _number_key(n) or ())


def _section_refs(
    draft: GraphDraft,
    node: NodeDraft,
    sections: SectionIndex,
    claimed: list[tuple[int, int]],
) -> list[ResolvedRef]:
    text = node.text
    cites = find_citations(text)
    skip = [(c.span.start, c.span.end) for c in cites]
    skip += [(q.start, q.refs_end) for q in qualified_refs(text, cites)]
    skip += claimed
    refs: list[ResolvedRef] = []
    for m in REF_LIST.finditer(text):
        if any(m.start() < e and s < m.end() for s, e in skip):
            continue
        counter = counter_of(m.group("word"))
        this = after_this(text, m)
        previous: PrintedRef | None = None
        for printed in split_refs(text, m):
            span = Span.of(text, printed.start, printed.end)
            target = _resolve(sections, counter, printed.ref)
            if target is None:
                _unresolved(draft, node, span, SECTION_RULE, "no heading carries this number")
            elif not (this and target == node.section) and target != node.id:
                refs.append(ResolvedRef(node.id, target, span, printed.ref, SECTION_RULE))
            if printed.range_end and previous is not None:
                whole = Span.of(text, previous.start, printed.end)
                for number in _between(sections, previous.ref, printed.ref):
                    inner = sections.find(counter, number)
                    if inner is not None and inner != node.id:
                        refs.append(ResolvedRef(node.id, inner, whole, number, SECTION_RULE))
            previous = printed
    return refs


def _positional_refs(node: NodeDraft, siblings: list[NodeDraft]) -> list[ResolvedRef]:
    refs: list[ResolvedRef] = []
    here = next(i for i, n in enumerate(siblings) if n.id == node.id)
    for m in _POSITIONAL.finditer(node.text):
        direction = (m.group("dir1") or m.group("dir2")).lower()
        what = (m.group("what1") or m.group("what2")).lower()
        kind = NodeKind.LIST_ITEM if what == "list" else NodeKind.TABLE
        if direction in _FORWARD:
            window = siblings[here + 1 : here + 1 + _REACH]
        else:
            window = list(reversed(siblings[max(0, here - _REACH) : here]))
        target = next((n for n in window if n.kind is kind), None)
        if target is None:
            continue
        span = Span.of(node.text, m.start(), m.end())
        refs.append(ResolvedRef(node.id, target.id, span, span.quote, POSITIONAL_RULE, weak=True))
    return refs


def link_references(draft: GraphDraft, sections: SectionIndex) -> list[ResolvedRef]:
    """Resolve every section, caption and positional reference; flag the misses."""
    index = _caption_index(draft)
    content = content_nodes(draft)
    refs: list[ResolvedRef] = []
    for node in content:
        claimed: list[tuple[int, int]] = []
        refs += _caption_refs(draft, node, index, claimed)
        refs += _section_refs(draft, node, sections, claimed)
        siblings = [n for n in content if n.section == node.section]
        refs += _positional_refs(node, siblings)
    return refs


def emit_references(draft: GraphDraft, refs: list[ResolvedRef], consumed: set[ResolvedRef]) -> None:
    """Add a `refers_to` edge for every resolved reference no precedence rule consumed."""
    for ref in refs:
        if ref in consumed:
            continue
        draft.add_edge(
            EdgeDraft(
                type=EdgeType.REFERS_TO,
                source=ref.node,
                target=ref.target,
                basis=Basis.EXPLICIT,
                method=ref.rule,
                made_by=rule(ref.rule),
                evidence=ref.span,
                label=ref.label,
                weak=ref.weak,
            ),
            stage=STAGE,
        )
