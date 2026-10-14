"""Literal graph builders for contract tests."""

from __future__ import annotations

from typing import Any

from inkthread.domain.model import (
    Actor,
    Basis,
    Confidence,
    DocumentInfo,
    Edge,
    EdgeType,
    Graph,
    GraphStats,
    Maker,
    Node,
    NodeKind,
    NodeSource,
    PageSize,
    Provenance,
    Region,
    Tier,
)

SHA = "a" * 64
RULE = Maker(actor=Actor.RULE, id="R-SEC-contains")
INK = Maker(actor=Actor.INKGRID, id="inkgrid")
OK = Confidence(tier=Tier.A, score=1.0, reasons=())


def node(
    nid: str,
    kind: NodeKind,
    text: str,
    order: int,
    section: str | None,
    depth: int,
    **extra: Any,
) -> Node:
    regions = (
        ()
        if kind in {NodeKind.DOCUMENT, NodeKind.TERM, NodeKind.EXTERNAL}
        else (Region(page=1, bbox=(10.0, 10.0, 100.0, 20.0)),)
    )
    fields: dict[str, Any] = {
        "id": nid,
        "kind": kind,
        "label": text[:80] or "doc.pdf",
        "label_truncated": len(text) > 80,
        "text": text,
        "order": order,
        "section": section,
        "depth": depth,
        "regions": regions,
        "confidence": OK,
        "source": NodeSource(blocks=(f"b{order}",) if order else (), keys=()),
        "made_by": INK,
    }
    fields.update(extra)
    return Node(**fields)


def edge(
    etype: EdgeType, source: str, target: str, method: str = "R-SEC-contains", **extra: Any
) -> Edge:
    return Edge.make(
        type=etype,
        source=source,
        target=target,
        basis=Basis.EXPLICIT,
        method=method,
        made_by=extra.pop("made_by", RULE),
        confidence=OK,
        **extra,
    )


def minimal_parts() -> tuple[list[Node], list[Edge]]:
    nodes = [
        node("d:doc", NodeKind.DOCUMENT, "", 0, None, 0),
        node("s:one", NodeKind.SECTION, "1 Fees", 1, "d:doc", 1),
        node("p:one", NodeKind.PARAGRAPH, "Members must pay.", 2, "s:one", 2),
    ]
    edges = [
        edge(EdgeType.CONTAINS, "d:doc", "s:one"),
        edge(EdgeType.CONTAINS, "s:one", "p:one"),
    ]
    return nodes, edges


def graph(nodes: list[Node], edges: list[Edge]) -> Graph:
    return Graph(
        document=DocumentInfo(
            sha256=SHA,
            file_name="doc.pdf",
            title=None,
            title_node=None,
            page_count=1,
            pages=(PageSize(number=1, width=612.0, height=792.0),),
        ),
        nodes=tuple(nodes),
        edges=tuple(edges),
        set_aside=(),
        findings=(),
        stats=GraphStats(nodes_by_kind={}, edges_by_type={}, roles={}, tiers={}),
        provenance=Provenance(
            pipeline_version="1.0.0",
            inkgrid_version="0.1.0",
            prompts_hash="",
            models={},
            ops_head="",
            ops_count=0,
            graph_hash="",
            rejected=(),
        ),
    )
