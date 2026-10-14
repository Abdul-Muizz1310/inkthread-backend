"""Cypher export (spec 09 § 3): an idempotent MERGE script for Neo4j, Memgraph and FalkorDB."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import assert_never

from inkthread.domain.model import Edge, Graph, Node, NodeKind

CONSTRAINT = (
    "CREATE CONSTRAINT inkthread_id IF NOT EXISTS FOR (n:Inkthread) REQUIRE n.id IS UNIQUE;"
)

_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"})

Value = str | int | float | Sequence[str] | None


def cypher_string(text: str) -> str:
    """A double-quoted Cypher string literal that reads back to `text`."""
    return '"' + text.translate(_ESCAPES) + '"'


def kind_label(kind: NodeKind) -> str:
    """The Neo4j label of a node kind."""
    match kind:
        case NodeKind.DOCUMENT:
            return "Document"
        case NodeKind.SECTION:
            return "Section"
        case NodeKind.PARAGRAPH:
            return "Paragraph"
        case NodeKind.LIST_ITEM:
            return "ListItem"
        case NodeKind.TABLE:
            return "Table"
        case NodeKind.NOTE:
            return "Note"
        case NodeKind.DEFINITION:
            return "Definition"
        case NodeKind.TERM:
            return "Term"
        case NodeKind.EXTERNAL:
            return "External"
        case _:
            assert_never(kind)


def _value(value: str | float | Sequence[str]) -> str:
    if isinstance(value, str):
        return cypher_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return "[" + ", ".join(cypher_string(v) for v in value) + "]"


def _props(props: Mapping[str, Value]) -> str:
    return "{" + ", ".join(f"{k}: {_value(v)}" for k, v in props.items() if v is not None) + "}"


def _node(n: Node) -> str:
    props: dict[str, Value] = {
        "kind": n.kind.value,
        "label": n.label,
        "text": n.text,
        "order": n.order,
        "depth": n.depth,
        "section": n.section,
        "page": n.regions[0].page if n.regions else None,
        "marker": n.marker,
        "roles": [a.role.value for a in n.roles],
        "tier": n.confidence.tier.value,
        "score": n.confidence.score,
    }
    return (
        f"MERGE (n:Inkthread:{kind_label(n.kind)} {{id: {cypher_string(n.id)}}}) "
        f"SET n += {_props(props)};"
    )


def _edge(e: Edge) -> str:
    props: dict[str, Value] = {
        "family": e.family.value,
        "basis": e.basis.value,
        "method": e.method,
        "label": e.label,
        "evidence": e.evidence.quote if e.evidence is not None else None,
        "evidence_on": e.evidence_on.value,
        "tier": e.confidence.tier.value,
        "score": e.confidence.score,
    }
    return (
        f"MATCH (a:Inkthread {{id: {cypher_string(e.source)}}}), "
        f"(b:Inkthread {{id: {cypher_string(e.target)}}}) "
        f"MERGE (a)-[r:{e.type.value.upper()} {{id: {cypher_string(e.id)}}}]->(b) "
        f"SET r += {_props(props)};"
    )


def to_cypher(graph: Graph) -> bytes:
    """The graph as a Cypher script; safe to run twice; the same graph gives the same bytes."""
    lines = [CONSTRAINT, *(_node(n) for n in graph.nodes), *(_edge(e) for e in graph.edges)]
    return ("\n".join(lines) + "\n").encode("utf-8")
