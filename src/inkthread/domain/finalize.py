"""Turn the mutable draft into the frozen, scored, attributed, hashed graph (spec 06)."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from inkthread.canon import cjson, sha256_hex
from inkthread.domain.confidence import score_edge, score_node, score_role
from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.explain import Violation, explain
from inkthread.domain.model import (
    EDGE_FAMILY,
    EDGE_ORDER,
    ROLE_ORDER,
    DocumentInfo,
    Edge,
    EdgeType,
    Flag,
    Graph,
    GraphStats,
    Node,
    NodeKind,
    NodeSource,
    Provenance,
    Role,
    RoleAssignment,
    Tier,
)
from inkthread.domain.ops import Op, chain, genesis
from inkthread.domain.reading import Reading
from inkthread.domain.text import cut_label


class ExplainFailed(Exception):  # noqa: N818 - the job failure code is `explain_failed`
    """The op log and the reading cannot account for the graph: a pipeline bug."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        summary = "; ".join(f"{v.check} {v.element}: {v.detail}" for v in violations[:5])
        super().__init__(f"{len(violations)} explain violation(s): {summary}")


@dataclass(frozen=True)
class FinalGraph:
    """The graph and the op log that explains it."""

    graph: Graph
    ops: tuple[Op, ...]


def hash_graph_json(data: Mapping[str, Any]) -> str:
    """`sha256(cjson(graph JSON with provenance.graph_hash set to ""))` (spec 06 § 5)."""
    blank = copy.deepcopy(dict(data))
    blank["provenance"] = {**blank["provenance"], "graph_hash": ""}
    return sha256_hex(cjson(blank))


def _flags(flags: Iterable[Flag]) -> tuple[Flag, ...]:
    return tuple(sorted(set(flags), key=lambda f: (f.code.value, f.detail or "")))


def _node(d: NodeDraft, *, verified: bool) -> Node:
    if d.kind is NodeKind.DOCUMENT and d.label is not None:
        label, truncated = d.label, len(d.label) < len(d.text)
    else:
        label, truncated = cut_label(d.text)
    roles = tuple(
        RoleAssignment(
            role=r.role,
            evidence=r.evidence,
            made_by=r.made_by,
            basis=r.basis,
            confidence=score_role(r),
            verdict=r.verdict,
        )
        for r in sorted(d.roles.values(), key=lambda r: ROLE_ORDER[r.role])
    )
    return Node(
        id=d.id,
        kind=d.kind,
        label=label,
        label_truncated=truncated,
        text=d.text,
        order=d.order,
        section=d.section,
        depth=d.depth,
        regions=tuple(d.regions),
        roles=roles,
        table=d.table,
        marker=d.marker,
        flags=_flags(d.flags),
        hidden_spans=tuple(d.hidden_spans),
        unresolved=tuple(d.unresolved),
        confidence=score_node(d, verified=verified),
        source=NodeSource(blocks=tuple(d.source_blocks), keys=tuple(d.source_keys)),
        made_by=d.made_by,
    )


def _edge(d: EdgeDraft, target: NodeDraft) -> Edge:
    return Edge(
        id=d.id,
        type=d.type,
        family=EDGE_FAMILY[d.type],
        source=d.source,
        target=d.target,
        basis=d.basis,
        evidence=d.evidence,
        evidence_on=d.evidence_on,
        anchor=d.anchor,
        label=d.label,
        method=d.method,
        made_by=d.made_by,
        confidence=score_edge(d, target),
        flags=_flags(d.flags),
        verdict=d.verdict,
    )


def graph_stats(nodes: Iterable[Node], edges: Iterable[Edge]) -> GraphStats:
    """Counts of the content. Every enum member is a key, so the shape never varies.

    `tiers` counts the tier of every node, every edge and every role assignment.
    """
    nodes, edges = list(nodes), list(edges)
    kinds = Counter(n.kind for n in nodes)
    types = Counter(e.type for e in edges)
    roles = Counter(a.role for n in nodes for a in n.roles)
    tiers = Counter(
        [n.confidence.tier for n in nodes]
        + [e.confidence.tier for e in edges]
        + [a.confidence.tier for n in nodes for a in n.roles]
    )
    return GraphStats(
        nodes_by_kind={k.value: kinds[k] for k in NodeKind},
        edges_by_type={t.value: types[t] for t in EdgeType},
        roles={r.value: roles[r] for r in Role},
        tiers={t.value: tiers[t] for t in Tier},
    )


def finalize(
    draft: GraphDraft,
    reading: Reading,
    *,
    inkgrid_version: str,
    prompts_hash: str,
    models: Mapping[str, str],
) -> FinalGraph:
    """Freeze, score and hash the draft, then prove the op log explains it.

    Raises `ExplainFailed` when any explain check fails, and ValueError (from the contract) when
    the draft breaks a graph invariant.
    """
    drafts = sorted(draft.nodes.values(), key=lambda n: n.order)
    nodes = [_node(d, verified=reading.verified) for d in drafts]
    order = {n.id: n.order for n in drafts}
    edges = [
        _edge(e, draft.nodes[e.target])
        for e in sorted(
            draft.edges.values(),
            key=lambda e: (EDGE_ORDER[e.type], order[e.source], order[e.target], e.id),
        )
    ]
    doc = next((n for n in nodes if n.kind is NodeKind.DOCUMENT), None)
    title = doc.text if doc is not None and doc.text else None
    block_index = {b.id: i for i, b in enumerate(reading.blocks)}
    set_aside = sorted(draft.set_aside, key=lambda s: block_index.get(s.block, len(block_index)))
    ops = tuple(draft.ops)
    unhashed = Graph(
        document=DocumentInfo(
            sha256=draft.sha256,
            file_name=draft.file_name,
            title=title,
            title_node=doc.id if title is not None and doc is not None else None,
            page_count=len(reading.pages),
            pages=reading.pages,
        ),
        nodes=tuple(nodes),
        edges=tuple(edges),
        set_aside=tuple(set_aside),
        findings=tuple(draft.findings),
        stats=graph_stats(nodes, edges),
        provenance=Provenance(
            pipeline_version=draft.pipeline_version,
            inkgrid_version=inkgrid_version,
            prompts_hash=prompts_hash,
            models=dict(models),
            ops_head=chain(ops, genesis(draft.sha256, draft.pipeline_version)),
            ops_count=len(ops),
            graph_hash="",
            rejected=tuple(draft.rejected),
        ),
    )
    digest = hash_graph_json(unhashed.model_dump(mode="json", by_alias=True))
    graph = unhashed.model_copy(
        update={"provenance": unhashed.provenance.model_copy(update={"graph_hash": digest})}
    )
    violations = explain(graph, reading, ops)
    if violations:
        raise ExplainFailed(violations)
    return FinalGraph(graph=graph, ops=ops)
