"""GraphML export (spec 09 § 2) for Gephi, yEd and Cytoscape."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence

from inkthread.domain.model import Edge, Graph, Node

NS = "http://graphml.graphdrawing.org/xmlns"

_ILLEGAL = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")

NODE_KEYS: Sequence[tuple[str, str]] = (
    ("kind", "string"),
    ("label", "string"),
    ("text", "string"),
    ("roles", "string"),
    ("tier", "string"),
    ("score", "double"),
    ("page", "string"),
    ("section", "string"),
)
EDGE_KEYS: Sequence[tuple[str, str]] = (
    ("type", "string"),
    ("family", "string"),
    ("basis", "string"),
    ("method", "string"),
    ("tier", "string"),
    ("score", "double"),
    ("label", "string"),
    ("evidence", "string"),
)


def xml_safe(text: str) -> str:
    """Drop the characters XML 1.0 forbids; escaping the rest is the serializer's job."""
    return _ILLEGAL.sub("", text)


def _node_values(n: Node) -> dict[str, str]:
    return {
        "kind": n.kind.value,
        "label": n.label,
        "text": n.text,
        "roles": ",".join(a.role.value for a in n.roles),
        "tier": n.confidence.tier.value,
        "score": repr(n.confidence.score),
        "page": str(n.regions[0].page) if n.regions else "",
        "section": n.section or "",
    }


def _edge_values(e: Edge) -> dict[str, str]:
    return {
        "type": e.type.value,
        "family": e.family.value,
        "basis": e.basis.value,
        "method": e.method,
        "tier": e.confidence.tier.value,
        "score": repr(e.confidence.score),
        "label": e.label or "",
        "evidence": e.evidence.quote if e.evidence is not None else "",
    }


def _data(parent: ET.Element, prefix: str, values: dict[str, str]) -> None:
    for name, value in values.items():
        el = ET.SubElement(parent, "data", key=f"{prefix}_{name}")
        el.text = xml_safe(value)


def to_graphml(graph: Graph) -> bytes:
    """The graph as GraphML bytes; the same graph gives the same bytes."""
    root = ET.Element("graphml", xmlns=NS)
    for prefix, domain, keys in (("n", "node", NODE_KEYS), ("e", "edge", EDGE_KEYS)):
        for name, kind in keys:
            ET.SubElement(
                root,
                "key",
                {
                    "id": f"{prefix}_{name}",
                    "for": domain,
                    "attr.name": name,
                    "attr.type": kind,
                },
            )
    g = ET.SubElement(root, "graph", id="G", edgedefault="directed")
    for n in graph.nodes:
        _data(ET.SubElement(g, "node", id=xml_safe(n.id)), "n", _node_values(n))
    for e in graph.edges:
        el = ET.SubElement(
            g, "edge", id=xml_safe(e.id), source=xml_safe(e.source), target=xml_safe(e.target)
        )
        _data(el, "e", _edge_values(e))
    ET.indent(root)
    raw: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return raw + b"\n"
