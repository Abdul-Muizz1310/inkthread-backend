"""The mutable draft the pipeline stages fill in, recording an op for every change.

Stages are pure functions over a draft: they add nodes, edges, roles, flags and unresolved entries,
and the draft appends one `Op` per successful change. `finalize` turns the draft into a frozen
`Graph` (spec 06).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from inkthread.canon import sha256_hex
from inkthread.domain.ids import edge_id
from inkthread.domain.model import (
    Anchor,
    Basis,
    EdgeType,
    EvidenceSide,
    Finding,
    Flag,
    Maker,
    NodeKind,
    Region,
    RejectedClaim,
    Role,
    SetAside,
    Span,
    TableInfo,
    Unresolved,
    Verdict,
)
from inkthread.domain.ops import Op, OpKind


@dataclass
class RoleDraft:
    """A role on its way into the graph."""

    role: Role
    evidence: Span | None
    made_by: Maker
    basis: Basis
    weak: bool = False
    verdict: Verdict | None = None


@dataclass
class NodeDraft:
    """A node on its way into the graph."""

    id: str
    kind: NodeKind
    text: str
    order: int
    section: str | None
    depth: int
    regions: list[Region]
    made_by: Maker
    table: TableInfo | None = None
    marker: str | None = None
    label: str | None = None
    source_blocks: list[str] = field(default_factory=list)
    source_keys: list[str] = field(default_factory=list)
    roles: dict[Role, RoleDraft] = field(default_factory=dict)
    flags: list[Flag] = field(default_factory=list)
    hidden_spans: list[Span] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)

    def has_flag(self, code: str) -> bool:
        """Whether the node carries a flag with this code."""
        return any(f.code == code for f in self.flags)


@dataclass
class EdgeDraft:
    """An edge on its way into the graph."""

    type: EdgeType
    source: str
    target: str
    basis: Basis
    method: str
    made_by: Maker
    evidence: Span | None = None
    evidence_on: EvidenceSide = EvidenceSide.SOURCE
    anchor: Anchor | None = None
    label: str | None = None
    weak: bool = False
    flags: list[Flag] = field(default_factory=list)
    verdict: Verdict | None = None

    @property
    def id(self) -> str:
        """The content-derived edge id (spec 01 § 5)."""
        return edge_id(self.type.value, self.source, self.target, self.method, self.label)


@dataclass
class Delta:
    """What changed since the last `take_delta` (it feeds the live event stream)."""

    nodes: list[NodeDraft] = field(default_factory=list)
    edges: list[EdgeDraft] = field(default_factory=list)
    roles: list[tuple[str, RoleDraft]] = field(default_factory=list)
    flags: list[tuple[str, Flag]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """Whether nothing changed."""
        return not (self.nodes or self.edges or self.roles or self.flags)


@dataclass
class GraphDraft:
    """Nodes, edges and everything else the stages add, plus the op log of those additions."""

    sha256: str
    pipeline_version: str
    file_name: str | None = None
    nodes: dict[str, NodeDraft] = field(default_factory=dict)
    edges: dict[str, EdgeDraft] = field(default_factory=dict)
    set_aside: list[SetAside] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    rejected: list[RejectedClaim] = field(default_factory=list)
    ops: list[Op] = field(default_factory=list)
    _delta: Delta = field(default_factory=Delta)

    def _op(
        self, kind: OpKind, target: str, stage: str, maker: Maker, detail: str | None = None
    ) -> None:
        self.ops.append(
            Op(
                seq=len(self.ops) + 1,
                stage=stage,
                kind=kind,
                target=target,
                actor=maker.actor.value,
                method=maker.id,
                model=maker.model,
                request_key=maker.request_key,
                detail=detail,
            )
        )

    def node(self, node_id: str) -> NodeDraft:
        """The node with this id; a KeyError names a bug in the caller."""
        return self.nodes[node_id]

    def add_node(self, node: NodeDraft, *, stage: str) -> None:
        """Add a node; a duplicate id is a bug and raises."""
        if node.id in self.nodes:
            msg = f"duplicate node id {node.id}"
            raise ValueError(msg)
        self.nodes[node.id] = node
        self._op("add_node", node.id, stage, node.made_by, node.kind.value)
        self._delta.nodes.append(node)

    def add_edge(self, edge: EdgeDraft, *, stage: str) -> bool:
        """Add an edge; returns False (and records nothing) when its id already exists."""
        if edge.source == edge.target:
            msg = f"an edge may not loop ({edge.source})"
            raise ValueError(msg)
        for end in (edge.source, edge.target):
            if end not in self.nodes:
                msg = f"edge names unknown node {end}"
                raise ValueError(msg)
        if edge.id in self.edges:
            return False
        self.edges[edge.id] = edge
        detail = edge.type.value
        if edge.evidence is not None:
            detail += f" {edge.evidence.start}-{edge.evidence.end}"
        self._op("add_edge", edge.id, stage, edge.made_by, detail)
        self._delta.edges.append(edge)
        return True

    def add_role(self, node_id: str, role: RoleDraft, *, stage: str) -> bool:
        """Add a role; returns False when the node already has it."""
        node = self.nodes[node_id]
        if role.role in node.roles:
            return False
        if role.evidence is not None and not role.evidence.fits(node.text):
            msg = f"role evidence does not fit the text of {node_id}"
            raise ValueError(msg)
        node.roles[role.role] = role
        detail = None
        if role.evidence is not None:
            detail = f"{role.evidence.start}-{role.evidence.end}"
        self._op("add_role", f"{node_id}#{role.role.value}", stage, role.made_by, detail)
        self._delta.roles.append((node_id, role))
        return True

    def add_flag(self, node_id: str, flag: Flag, *, stage: str, maker: Maker | None = None) -> bool:
        """Add a flag; returns False when the same (code, detail) is already there."""
        node = self.nodes[node_id]
        if flag in node.flags:
            return False
        node.flags.append(flag)
        self._op("add_flag", node_id, stage, maker or node.made_by, flag.code.value)
        self._delta.flags.append((node_id, flag))
        return True

    def add_unresolved(self, node_id: str, entry: Unresolved, *, stage: str, maker: Maker) -> None:
        """Record a call or reference that found no target."""
        node = self.nodes[node_id]
        node.unresolved.append(entry)
        self._op("add_unresolved", node_id, stage, maker, sha256_hex(entry.text))

    def set_aside_block(self, entry: SetAside, *, stage: str, maker: Maker) -> None:
        """Keep a non-content block, verbatim, outside the graph's nodes."""
        self.set_aside.append(entry)
        self._op("set_aside", entry.block, stage, maker, entry.kind)

    def set_role_verdict(
        self, node_id: str, role: Role, verdict: Verdict, *, stage: str, maker: Maker
    ) -> None:
        """Attach a verifier verdict to an agent-made role."""
        self.nodes[node_id].roles[role].verdict = verdict
        self._op("verdict", f"{node_id}#{role.value}", stage, maker, verdict.verdict)

    def set_edge_verdict(
        self, edge_id_: str, verdict: Verdict, *, stage: str, maker: Maker
    ) -> None:
        """Attach a verifier verdict to an agent-made edge."""
        self.edges[edge_id_].verdict = verdict
        self._op("verdict", edge_id_, stage, maker, verdict.verdict)

    def reject(self, claim: RejectedClaim, *, stage: str, maker: Maker) -> None:
        """Record a model claim that failed grounding."""
        self.rejected.append(claim)
        self._op("reject", f"{claim.task}:{claim.request_key[:12]}", stage, maker, claim.reason)

    def take_delta(self) -> Delta:
        """Everything added since the previous call."""
        delta, self._delta = self._delta, Delta()
        return delta

    def nodes_of(self, *kinds: NodeKind) -> list[NodeDraft]:
        """Nodes of the given kinds, in reading order."""
        wanted = set(kinds)
        return sorted((n for n in self.nodes.values() if n.kind in wanted), key=lambda n: n.order)
