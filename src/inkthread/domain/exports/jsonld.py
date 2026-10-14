"""JSON-LD export (spec 09 § 1): nodes with their direct relations, and edges as assertions.

The `@context` is inline, so reading the export needs no network.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, assert_never

from inkthread.domain.model import Edge, EdgeType, Graph, Node, NodeKind, Region

NS = "https://github.com/Abdul-Muizz1310/inkthread-backend/ns#"
RFC8118 = "http://tools.ietf.org/rfc/rfc8118"

CONTEXT: Mapping[str, str] = {
    "ink": NS,
    "schema": "http://schema.org/",
    "doco": "http://purl.org/spar/doco/",
    "po": "http://www.essepuntato.it/2008/12/pattern#",
    "dcterms": "http://purl.org/dc/terms/",
    "cito": "http://purl.org/spar/cito/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
    "oa": "http://www.w3.org/ns/oa#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
}


def node_types(kind: NodeKind) -> list[str]:
    """The JSON-LD types of a node kind."""
    match kind:
        case NodeKind.DOCUMENT:
            return ["ink:Document", "schema:CreativeWork"]
        case NodeKind.SECTION:
            return ["ink:Section", "doco:Section"]
        case NodeKind.PARAGRAPH:
            return ["ink:Paragraph", "doco:Paragraph"]
        case NodeKind.LIST_ITEM:
            return ["ink:ListItem", "doco:Paragraph"]
        case NodeKind.TABLE:
            return ["ink:Table", "doco:Table"]
        case NodeKind.NOTE:
            return ["ink:Note", "doco:Footnote"]
        case NodeKind.DEFINITION:
            return ["ink:Definition", "doco:Glossary"]
        case NodeKind.TERM:
            return ["ink:Term", "schema:DefinedTerm", "skos:Concept"]
        case NodeKind.EXTERNAL:
            return ["ink:External", "schema:CreativeWork"]
        case _:
            assert_never(kind)


def predicate(edge_type: EdgeType) -> str:
    """The JSON-LD property of an edge type."""
    match edge_type:
        case EdgeType.CONTAINS:
            return "po:contains"
        case EdgeType.CONTINUES:
            return "ink:continues"
        case EdgeType.CITES_NOTE:
            return "ink:citesNote"
        case EdgeType.DEFINES:
            return "ink:defines"
        case EdgeType.USES_TERM:
            return "ink:usesTerm"
        case EdgeType.REFERS_TO:
            return "dcterms:references"
        case EdgeType.CITES_EXTERNAL:
            return "cito:cites"
        case EdgeType.GOVERNS:
            return "ink:governs"
        case EdgeType.QUALIFIES:
            return "ink:qualifies"
        case EdgeType.OVERRIDES:
            return "ink:overrides"
        case EdgeType.ILLUSTRATES:
            return "ink:illustrates"
        case _:
            assert_never(edge_type)


def _num(value: float) -> str:
    return repr(float(value)).removesuffix(".0")


def fragment(region: Region) -> str:
    """An RFC 8118 PDF fragment: `page=<n>&viewrect=<left>,<top>,<width>,<height>`."""
    x0, y0, x1, y1 = region.bbox
    rect = ",".join(_num(v) for v in (x0, y0, x1 - x0, y1 - y0))
    return f"page={region.page}&viewrect={rect}"


def _ref(prefix: str, ident: str) -> dict[str, str]:
    return {"@id": f"ink:{prefix}/{ident}"}


def _node(n: Node, out_edges: list[Edge]) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "@id": f"ink:node/{n.id}",
        "@type": node_types(n.kind),
        "ink:kind": n.kind.value,
        "ink:label": n.label,
        "ink:text": n.text,
        "ink:order": n.order,
        "ink:depth": n.depth,
        "ink:tier": n.confidence.tier.value,
        "ink:score": n.confidence.score,
    }
    if n.section is not None:
        obj["ink:section"] = _ref("node", n.section)
    if n.roles:
        obj["ink:role"] = [{"@id": f"ink:role/{a.role.value}"} for a in n.roles]
    if n.regions:
        obj["prov:wasDerivedFrom"] = [
            {
                "@type": "oa:SpecificResource",
                "oa:hasSelector": {
                    "@type": "oa:FragmentSelector",
                    "dcterms:conformsTo": {"@id": RFC8118},
                    "rdf:value": fragment(r),
                },
            }
            for r in n.regions
        ]
    for e in out_edges:
        obj.setdefault(predicate(e.type), []).append(_ref("node", e.target))
    return obj


def _edge(e: Edge) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "@id": f"ink:edge/{e.id}",
        "@type": ["ink:Assertion"],
        "ink:subject": _ref("node", e.source),
        "ink:predicate": {"@id": predicate(e.type)},
        "ink:object": _ref("node", e.target),
        "ink:basis": e.basis.value,
        "ink:tier": e.confidence.tier.value,
        "ink:score": e.confidence.score,
        "ink:method": e.method,
    }
    if e.label is not None:
        obj["ink:label"] = e.label
    if e.evidence is not None:
        obj["ink:evidence"] = [
            {"@type": "oa:TextQuoteSelector", "oa:exact": e.evidence.quote},
            {
                "@type": "oa:TextPositionSelector",
                "oa:start": e.evidence.start,
                "oa:end": e.evidence.end,
            },
        ]
    return obj


def to_jsonld(graph: Graph) -> bytes:
    """The graph as JSON-LD bytes; the same graph gives the same bytes."""
    out: dict[str, list[Edge]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        out[e.source].append(e)
    doc = {
        "@context": dict(CONTEXT),
        "@graph": [_node(n, out[n.id]) for n in graph.nodes] + [_edge(e) for e in graph.edges],
    }
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)
    return (text + "\n").encode("utf-8")
