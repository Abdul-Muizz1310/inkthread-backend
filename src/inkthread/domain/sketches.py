"""The small shapes the event stream sends to animate a build (spec 07 § 3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from inkthread.domain.draft import Delta
from inkthread.domain.model import Basis, EdgeType, FlagCode, NodeKind, Role
from inkthread.domain.text import cut_label


class _Sketch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NodeSketch(_Sketch):
    """A node, just enough to draw it."""

    id: str
    kind: NodeKind
    label: str
    section: str | None
    depth: int
    order: int
    page: int | None


class EdgeSketch(_Sketch):
    """An edge, just enough to draw it."""

    id: str
    type: EdgeType
    source: str
    target: str
    basis: Basis


class RoleSketch(_Sketch):
    """A role landing on a node."""

    node: str
    role: Role
    basis: Basis


class FlagSketch(_Sketch):
    """A flag landing on a node."""

    node: str
    code: FlagCode


class SketchBatch(_Sketch):
    """Everything one stage added since the last batch."""

    stage: str
    nodes: tuple[NodeSketch, ...] = ()
    edges: tuple[EdgeSketch, ...] = ()
    roles: tuple[RoleSketch, ...] = ()
    flags: tuple[FlagSketch, ...] = ()


def sketch(delta: Delta, stage: str) -> SketchBatch:
    """Sketch a draft delta for the `delta` event."""
    return SketchBatch(
        stage=stage,
        nodes=tuple(
            NodeSketch(
                id=n.id,
                kind=n.kind,
                label=n.label if n.label is not None else cut_label(n.text)[0],
                section=n.section,
                depth=n.depth,
                order=n.order,
                page=n.regions[0].page if n.regions else None,
            )
            for n in delta.nodes
        ),
        edges=tuple(
            EdgeSketch(id=e.id, type=e.type, source=e.source, target=e.target, basis=e.basis)
            for e in delta.edges
        ),
        roles=tuple(RoleSketch(node=nid, role=r.role, basis=r.basis) for nid, r in delta.roles),
        flags=tuple(FlagSketch(node=nid, code=f.code) for nid, f in delta.flags),
    )
