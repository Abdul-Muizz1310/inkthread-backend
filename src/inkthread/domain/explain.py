"""The explain gate (spec 06 § 4): proof that the op log and the reading account for the graph.

Any violation fails the job: a graph the log cannot account for is a bug, never a warning.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from inkthread.domain.model import (
    PART_KINDS,
    EvidenceSide,
    Graph,
    Maker,
    Node,
    NodeKind,
    Span,
)
from inkthread.domain.ops import Op
from inkthread.domain.reading import Reading

_PLACED = PART_KINDS | {NodeKind.SECTION}


class Violation(BaseModel):
    """One failed check: which check, on which element, and what was wrong."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    element: str
    detail: str


def role_key(node_id: str, role: str) -> str:
    """The element id of a role assignment, as ops and `why` name it."""
    return f"{node_id}#{role}"


def reject_key(task: str, request_key: str) -> str:
    """The op target a rejected claim is recorded under (mirrors `GraphDraft.reject`)."""
    return f"{task}:{request_key[:12]}"


def _x1_verbatim(graph: Graph, reading: Reading) -> Iterator[Violation]:
    texts = {b.id: b.text for b in reading.blocks}
    parts = [n.text for n in graph.nodes if n.kind in PART_KINDS]
    for n in graph.nodes:
        if n.kind is NodeKind.DOCUMENT:
            first = texts.get(n.source.blocks[0]) if n.source.blocks else None
            if n.text and n.text != first:
                yield Violation(check="X1", element=n.id, detail="not its title block's text")
        elif n.kind in _PLACED:
            if any(b not in texts for b in n.source.blocks):
                continue  # an unknown block is X5's to report
            if n.text != "\n".join(texts[b] for b in n.source.blocks):
                yield Violation(check="X1", element=n.id, detail="not its blocks' text")
        elif not any(n.text in p for p in parts):
            yield Violation(check="X1", element=n.id, detail="text occurs in no part")


def _bad_span(span: Span | None, text: str) -> bool:
    return span is not None and not span.fits(text)


def _x2_spans(graph: Graph, nodes: Mapping[str, Node]) -> Iterator[Violation]:
    for n in graph.nodes:
        spans: list[tuple[str, Span | None]] = [
            (role_key(n.id, a.role.value), a.evidence) for a in n.roles
        ]
        spans += [(n.id, s) for s in n.hidden_spans]
        spans += [(n.id, u.span) for u in n.unresolved]
        for element, span in spans:
            if _bad_span(span, n.text):
                yield Violation(check="X2", element=element, detail="span does not fit the text")
    for e in graph.edges:
        holder = e.source if e.evidence_on is EvidenceSide.SOURCE else e.target
        if holder in nodes and _bad_span(e.evidence, nodes[holder].text):
            yield Violation(check="X2", element=e.id, detail=f"span does not fit {holder}")


def _x3_regions(graph: Graph) -> Iterator[Violation]:
    for n in graph.nodes:
        if n.kind in _PLACED and not n.regions:
            yield Violation(check="X3", element=n.id, detail="no page region")


def _x4_attribution(graph: Graph, ops: Sequence[Op]) -> Iterator[Violation]:
    creators: dict[tuple[str, str], list[Op]] = defaultdict(list)
    for o in ops:
        creators[o.kind, o.target].append(o)
    makers: list[tuple[str, str, Maker]] = []
    for n in graph.nodes:
        makers.append(("add_node", n.id, n.made_by))
        makers += [("add_role", role_key(n.id, a.role.value), a.made_by) for a in n.roles]
    makers += [("add_edge", e.id, e.made_by) for e in graph.edges]
    for kind, element, maker in makers:
        found = creators.get((kind, element), [])
        if len(found) != 1:
            yield Violation(check="X4", element=element, detail=f"{len(found)} creating ops")
        elif (found[0].actor, found[0].method) != (maker.actor.value, maker.id):
            yield Violation(check="X4", element=element, detail="creating op names another maker")
    known = {element for _, element, _ in makers}
    known |= {s.block for s in graph.set_aside}
    known |= {reject_key(r.task, r.request_key) for r in graph.provenance.rejected}
    for o in ops:
        if o.target not in known:
            yield Violation(check="X4", element=o.target, detail=f"op {o.seq} names no element")


def _x5_partition(graph: Graph, reading: Reading) -> Iterator[Violation]:
    cited: Counter[str] = Counter()
    for n in graph.nodes:
        cited.update(n.source.blocks)
    cited.update(s.block for s in graph.set_aside)
    blocks = [b.id for b in reading.blocks]
    for b in blocks:
        if cited[b] != 1:
            yield Violation(check="X5", element=b, detail=f"cited {cited[b]} times")
    for b in sorted(set(cited) - set(blocks)):
        yield Violation(check="X5", element=b, detail="not a block of the reading")


def _x6_gaps(graph: Graph, reading: Reading) -> Iterator[Violation]:
    set_aside = {s.block for s in graph.set_aside}
    owners: dict[str, list[Node]] = defaultdict(list)
    for n in graph.nodes:
        for b in n.source.blocks:
            owners[b].append(n)
    for link in reading.links:
        if link.kind != "footnote_call" or link.status != "unresolved":
            continue
        if link.from_block in set_aside:
            continue
        nodes = owners.get(link.from_block, [])
        if not nodes:
            continue  # an uncited block is X5's to report
        listed = [u for n in nodes for u in n.unresolved if u.kind == "note"]
        if not any(link.label is None or u.text == link.label for u in listed):
            yield Violation(
                check="X6",
                element=nodes[0].id,
                detail=f"unresolved call {link.label!r} not listed",
            )


def explain(graph: Graph, reading: Reading, ops: Sequence[Op]) -> list[Violation]:
    """Every way the graph fails checks X1-X6; empty when the log and reading account for it."""
    nodes = {n.id: n for n in graph.nodes}
    return [
        *_x1_verbatim(graph, reading),
        *_x2_spans(graph, nodes),
        *_x3_regions(graph),
        *_x4_attribution(graph, ops),
        *_x5_partition(graph, reading),
        *_x6_gaps(graph, reading),
    ]
