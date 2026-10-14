"""Why an element is in the graph (spec 06 § 6)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from inkthread.domain.catalog import RULES, TASKS
from inkthread.domain.explain import role_key
from inkthread.domain.model import Confidence, Graph, Maker, Reason, Span, Verdict
from inkthread.domain.ops import Op

UNKNOWN = "unknown rule"


class Why(BaseModel):
    """An element, its maker, what its rule or task does, its evidence and the ops behind it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    element: str
    kind: Literal["node", "edge", "role"]
    maker: Maker
    statement: str
    evidence: Span | None
    reasons: tuple[Reason, ...]
    verdict: Verdict | None
    ops: tuple[Op, ...]


def statement(rule_id: str) -> str:
    """The catalogue's one-line statement for a rule or agent task id."""
    return RULES.get(rule_id) or TASKS.get(rule_id) or UNKNOWN


def why(graph: Graph, ops: Sequence[Op], element_id: str) -> Why:
    """Explain one node, edge or `<node id>#<role>`; an unknown element raises KeyError."""
    kind: Literal["node", "edge", "role"]
    evidence: Span | None
    verdict: Verdict | None
    confidence: Confidence
    nodes = {n.id: n for n in graph.nodes}
    edges = {e.id: e for e in graph.edges}
    if element_id in nodes:
        n = nodes[element_id]
        kind, maker, evidence, verdict, confidence = "node", n.made_by, None, None, n.confidence
    elif element_id in edges:
        e = edges[element_id]
        kind, maker, evidence, verdict, confidence = (
            "edge",
            e.made_by,
            e.evidence,
            e.verdict,
            e.confidence,
        )
    else:
        node_id, _, role = element_id.partition("#")
        owner = nodes.get(node_id)
        found = [a for a in owner.roles if a.role.value == role] if owner is not None else []
        if not found:
            raise KeyError(element_id)
        a = found[0]
        kind, maker, evidence, verdict, confidence = (
            "role",
            a.made_by,
            a.evidence,
            a.verdict,
            a.confidence,
        )
        element_id = role_key(node_id, a.role.value)
    touched = tuple(sorted((o for o in ops if o.target == element_id), key=lambda o: o.seq))
    return Why(
        element=element_id,
        kind=kind,
        maker=maker,
        statement=statement(maker.id),
        evidence=evidence,
        reasons=confidence.reasons,
        verdict=verdict,
        ops=touched,
    )
