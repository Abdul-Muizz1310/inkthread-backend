"""Spec 06 § 3 (T-CP-4..6) and the draft's mutation contract."""

from __future__ import annotations

import pytest

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft, RoleDraft
from inkthread.domain.model import (
    Actor,
    Basis,
    EdgeType,
    Flag,
    FlagCode,
    Maker,
    NodeKind,
    Region,
    Role,
    Span,
)
from inkthread.domain.ops import Op, chain, genesis, verify

SHA = "b" * 64
RULE = Maker(actor=Actor.RULE, id="R-X")


def op(seq: int, target: str = "p:1", kind: str = "add_node") -> Op:
    return Op(seq=seq, stage="structure", kind=kind, target=target, actor="rule", method="R-X")


def test_head_is_deterministic_and_order_sensitive() -> None:  # T-CP-4
    ops = [op(1), op(2, "p:2")]
    g = genesis(SHA, "1.0.0")
    assert chain(ops, g) == chain(list(ops), g)
    assert chain(ops, g) != chain(list(reversed(ops)), g)
    assert chain([op(1), op(2, "p:3")], g) != chain(ops, g)


def test_verify_catches_tampering() -> None:  # T-CP-5
    ops = [op(1), op(2, "p:2"), op(3, "p:3")]
    head = chain(ops, genesis(SHA, "1.0.0"))
    assert verify(ops, head, 3, SHA, "1.0.0")
    assert not verify([op(1), op(2, "p:9"), op(3, "p:3")], head, 3, SHA, "1.0.0")
    assert not verify([ops[0], ops[2]], head, 3, SHA, "1.0.0")
    assert not verify(ops[:2], chain(ops[:2], genesis(SHA, "1.0.0")), 3, SHA, "1.0.0")
    assert not verify(ops, head, 3, "c" * 64, "1.0.0")


def para(nid: str, text: str, order: int) -> NodeDraft:
    return NodeDraft(
        id=nid,
        kind=NodeKind.PARAGRAPH,
        text=text,
        order=order,
        section="d:x",
        depth=1,
        regions=[Region(page=1, bbox=(0, 0, 1, 1))],
        made_by=RULE,
    )


def test_ops_hold_no_quote_text() -> None:  # T-CP-6
    d = GraphDraft(sha256=SHA, pipeline_version="1.0.0")
    d.add_node(para("p:1", "Members must pay the secret fee.", 1), stage="structure")
    d.add_role(
        "p:1",
        RoleDraft(
            role=Role.OBLIGATION,
            evidence=Span.of(d.nodes["p:1"].text, 8, 12),
            made_by=RULE,
            basis=Basis.EXPLICIT,
        ),
        stage="classify_rules",
    )
    dumped = "".join(o.model_dump_json() for o in d.ops)
    assert "must" not in dumped
    assert "secret" not in dumped


def test_every_mutation_adds_one_op_and_duplicates_none() -> None:
    d = GraphDraft(sha256=SHA, pipeline_version="1.0.0")
    d.add_node(para("p:1", "a b", 1), stage="structure")
    d.add_node(para("p:2", "c d", 2), stage="structure")
    with pytest.raises(ValueError, match="duplicate"):
        d.add_node(para("p:1", "a b", 3), stage="structure")
    e = EdgeDraft(
        type=EdgeType.REFERS_TO,
        source="p:1",
        target="p:2",
        basis=Basis.EXPLICIT,
        method="R-REF-section",
        made_by=RULE,
        label="Section 2",
    )
    assert d.add_edge(e, stage="link_rules")
    assert not d.add_edge(e, stage="link_rules")
    role = RoleDraft(role=Role.CLAIM, evidence=None, made_by=RULE, basis=Basis.EXPLICIT)
    assert d.add_role("p:1", role, stage="classify_rules")
    assert not d.add_role("p:1", role, stage="classify_rules")
    d.add_flag("p:1", Flag(code=FlagCode.HIDDEN_TEXT, detail="2"), stage="structure")
    d.add_flag("p:1", Flag(code=FlagCode.HIDDEN_TEXT, detail="2"), stage="structure")
    assert [o.kind for o in d.ops] == ["add_node", "add_node", "add_edge", "add_role", "add_flag"]
    assert [o.seq for o in d.ops] == [1, 2, 3, 4, 5]


def test_take_delta_returns_only_new_items() -> None:
    d = GraphDraft(sha256=SHA, pipeline_version="1.0.0")
    d.add_node(para("p:1", "a", 1), stage="structure")
    first = d.take_delta()
    assert [n.id for n in first.nodes] == ["p:1"]
    d.add_node(para("p:2", "b", 2), stage="structure")
    second = d.take_delta()
    assert [n.id for n in second.nodes] == ["p:2"]
    assert d.take_delta().empty
