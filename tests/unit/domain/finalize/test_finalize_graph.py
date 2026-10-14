"""Spec 06 § 4-6: finalize, the explain gate, the graph hash and why (T-CP-7…11)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from finalize_sample import P1, P2, Sample, sample
from hypothesis import given, settings
from hypothesis import strategies as st

from inkthread.canon import cjson, sha256_hex
from inkthread.domain.catalog import RULES, TASKS
from inkthread.domain.explain import Violation, explain
from inkthread.domain.finalize import ExplainFailed, FinalGraph, finalize, hash_graph_json
from inkthread.domain.model import (
    Actor,
    EdgeType,
    Graph,
    Node,
    NodeKind,
    ReasonCode,
    Role,
    Span,
    Tier,
)
from inkthread.domain.ops import Op, chain, genesis, verify
from inkthread.domain.why import why

MODELS = {"producer": "m/producer", "verifier": "m/verifier"}


def run(s: Sample) -> FinalGraph:
    return finalize(s.draft, s.reading, inkgrid_version="0.1.0", prompts_hash="ph", models=MODELS)


@pytest.fixture
def built() -> tuple[Sample, FinalGraph]:
    s = sample()
    return s, run(s)


def by_id(graph: Graph, nid: str) -> Node:
    return next(n for n in graph.nodes if n.id == nid)


# T-CP-7 -----------------------------------------------------------------------------------------


def test_realistic_draft_passes_all_checks(built: tuple[Sample, FinalGraph]) -> None:  # T-CP-7
    s, fg = built
    assert explain(fg.graph, s.reading, fg.ops) == []
    assert fg.ops == tuple(s.draft.ops)


def test_finalize_shapes_the_graph(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    g = fg.graph
    assert [n.order for n in g.nodes] == sorted(n.order for n in g.nodes)
    assert g.document.title == "Fee Schedule"
    assert g.document.title_node == s.doc
    assert g.document.page_count == 1
    assert g.document.file_name == "doc.pdf"
    assert by_id(g, s.doc).label == "Fee Schedule"
    p1 = by_id(g, s.p1)
    assert p1.label == P1
    assert not p1.label_truncated
    assert p1.confidence.tier is Tier.B
    assert ReasonCode.UNRESOLVED_PARTS in [r.code for r in p1.confidence.reasons]
    order = [(e.type, e.source, e.target) for e in g.edges]
    assert order[0][0] is EdgeType.CONTAINS
    assert [t for t, _, _ in order] == sorted(
        (t for t, _, _ in order), key=lambda t: list(EdgeType).index(t)
    )
    agent = next(e for e in g.edges if e.id == s.agent_edge)
    assert agent.confidence.tier is Tier.B
    assert agent.verdict is not None
    assert agent.verdict.verdict == "supported"
    p2 = by_id(g, s.p2)
    assert [a.role for a in p2.roles] == [Role.DEFINITION]
    assert p2.roles[0].confidence.tier is Tier.C
    assert [x.block for x in g.set_aside] == ["b2"]
    prov = g.provenance
    assert prov.ops_count == len(s.draft.ops)
    assert prov.ops_head == chain(s.draft.ops, genesis(s.reading.sha256, "1.0.0"))
    assert verify(fg.ops, prov.ops_head, prov.ops_count, s.reading.sha256, "1.0.0")
    assert (prov.inkgrid_version, prov.prompts_hash, prov.models) == ("0.1.0", "ph", MODELS)


def test_stats_count_content(built: tuple[Sample, FinalGraph]) -> None:
    _, fg = built
    st_ = fg.graph.stats
    assert st_.nodes_by_kind == {
        "document": 1,
        "section": 1,
        "paragraph": 2,
        "list_item": 0,
        "table": 1,
        "note": 1,
        "definition": 0,
        "term": 1,
        "external": 0,
    }
    assert st_.edges_by_type["contains"] == 5
    assert st_.edges_by_type["qualifies"] == 1
    assert sum(st_.edges_by_type.values()) == 9
    assert st_.roles["obligation"] == 1
    assert st_.roles["definition"] == 1
    assert sum(st_.roles.values()) == 2
    # tiers count nodes + edges + role assignments
    assert st_.tiers == {"A": 15, "B": 2, "C": 1, "D": 0}


def test_flags_are_sorted_and_unique() -> None:
    from inkthread.domain.model import Flag, FlagCode

    s = sample()
    node = s.draft.node(s.p2)
    node.flags.extend(
        [
            Flag(code=FlagCode.MERGED_HEADING, detail="b"),
            Flag(code=FlagCode.HIDDEN_TEXT),
            Flag(code=FlagCode.MERGED_HEADING, detail="a"),
            Flag(code=FlagCode.HIDDEN_TEXT),
        ]
    )
    flags = by_id(run(s).graph, s.p2).flags
    assert [(f.code.value, f.detail) for f in flags] == [
        ("hidden_text", None),
        ("merged_heading", "a"),
        ("merged_heading", "b"),
    ]


# T-CP-8 -----------------------------------------------------------------------------------------


def swap_node(g: Graph, node: Node) -> Graph:
    return g.model_copy(update={"nodes": tuple(node if n.id == node.id else n for n in g.nodes)})


def checks(vs: list[Violation]) -> set[str]:
    return {v.check for v in vs}


def test_x1_text_changed(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    tab = by_id(fg.graph, s.table)
    g = swap_node(fg.graph, tab.model_copy(update={"text": tab.text[:-1] + "9"}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X1"}
    term = by_id(fg.graph, s.term)
    g = swap_node(fg.graph, term.model_copy(update={"text": "Annual Fees"}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X1"}
    doc = by_id(fg.graph, s.doc)
    g = swap_node(fg.graph, doc.model_copy(update={"text": "Fee Schedul"}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X1"}


def test_x2_span_shifted(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    shifted = Span(start=1, end=11, quote=P2[0:10])
    edges = tuple(
        e.model_copy(update={"evidence": shifted}) if e.type is EdgeType.DEFINES else e
        for e in fg.graph.edges
    )
    g = fg.graph.model_copy(update={"edges": edges})
    assert checks(explain(g, s.reading, fg.ops)) == {"X2"}
    p1 = by_id(fg.graph, s.p1)
    role = p1.roles[0].model_copy(update={"evidence": Span(start=9, end=13, quote="must")})
    g = swap_node(fg.graph, p1.model_copy(update={"roles": (role,)}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X2"}
    assert P1[9:13] != "must"


def test_x3_part_without_region(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    g = swap_node(fg.graph, by_id(fg.graph, s.p2).model_copy(update={"regions": ()}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X3"}


def test_x4_attribution(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    no_op = tuple(o for o in fg.ops if o.target != s.agent_edge or o.kind != "add_edge")
    assert checks(explain(fg.graph, s.reading, no_op)) == {"X4"}
    ghost = Op(
        seq=len(fg.ops) + 1,
        stage="x",
        kind="add_flag",
        target="p:ghost",
        actor="rule",
        method="R-X",
    )
    assert checks(explain(fg.graph, s.reading, (*fg.ops, ghost))) == {"X4"}
    twice = (*fg.ops, next(o for o in fg.ops if o.kind == "add_node"))
    assert checks(explain(fg.graph, s.reading, twice)) == {"X4"}
    wrong = tuple(
        o.model_copy(update={"method": "R-OTHER"}) if o.target == f"{s.p1}#obligation" else o
        for o in fg.ops
    )
    assert checks(explain(fg.graph, s.reading, wrong)) == {"X4"}


def test_x5_partition(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    doc = by_id(fg.graph, s.doc)
    twice = doc.source.model_copy(update={"blocks": (*doc.source.blocks, "b2")})
    g = swap_node(fg.graph, doc.model_copy(update={"source": twice}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X5"}
    g = fg.graph.model_copy(update={"set_aside": ()})
    ops = tuple(o for o in fg.ops if o.kind != "set_aside")
    assert checks(explain(g, s.reading, ops)) == {"X5"}


def test_x6_unresolved_call_missing(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    g = swap_node(fg.graph, by_id(fg.graph, s.p1).model_copy(update={"unresolved": ()}))
    assert checks(explain(g, s.reading, fg.ops)) == {"X6"}


def test_finalize_raises_when_explain_fails() -> None:
    s = sample()
    s.draft.node(s.doc).source_blocks.append("b2")
    with pytest.raises(ExplainFailed) as err:
        run(s)
    assert {v.check for v in err.value.violations} == {"X5"}


# T-CP-9 / T-CP-10 -------------------------------------------------------------------------------


def test_same_input_same_hash_and_bytes() -> None:  # T-CP-9
    a, b = run(sample()).graph, run(sample()).graph
    assert a.provenance.graph_hash == b.provenance.graph_hash
    assert a.model_dump_json() == b.model_dump_json()
    data = a.model_dump(mode="json", by_alias=True)
    assert a.provenance.graph_hash == hash_graph_json(data)
    data["provenance"]["graph_hash"] = ""
    assert a.provenance.graph_hash == sha256_hex(cjson(data))


def leaves(obj: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in leaves(v, (*path, k))]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in leaves(v, (*path, i))]
    return [path]


GRAPH_JSON = run(sample()).graph.model_dump(mode="json", by_alias=True)
PATHS = [p for p in leaves(GRAPH_JSON) if p != ("provenance", "graph_hash")]


def mutate(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int | float):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    return "x"


@settings(max_examples=200, deadline=None)
@given(st.sampled_from(PATHS))
def test_hash_covers_every_field_but_itself(path: tuple[Any, ...]) -> None:  # T-CP-10
    data = json.loads(json.dumps(GRAPH_JSON))
    base = hash_graph_json(data)
    cursor = data
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = mutate(cursor[path[-1]])
    assert hash_graph_json(data) != base


def test_hash_ignores_its_own_field() -> None:  # T-CP-10
    data = json.loads(json.dumps(GRAPH_JSON))
    base = hash_graph_json(data)
    data["provenance"]["graph_hash"] = "anything"
    assert hash_graph_json(data) == base


# T-CP-11 ----------------------------------------------------------------------------------------


def test_why_rule_role(built: tuple[Sample, FinalGraph]) -> None:  # T-CP-11
    s, fg = built
    w = why(fg.graph, fg.ops, f"{s.p1}#obligation")
    assert w.kind == "role"
    assert w.statement == RULES["R-SEC-part"]
    assert w.maker.id == "R-SEC-part"
    assert w.evidence is not None
    assert w.evidence.quote == "must"
    assert [o.kind for o in w.ops] == ["add_role"]


def test_why_agent_edge(built: tuple[Sample, FinalGraph]) -> None:  # T-CP-11
    s, fg = built
    w = why(fg.graph, fg.ops, s.agent_edge)
    assert w.kind == "edge"
    assert w.statement == TASKS["A-relate"]
    assert (w.maker.actor, w.maker.model, w.maker.request_key) == (
        Actor.AGENT,
        "m/producer",
        "rk-relate",
    )
    assert w.verdict is not None
    assert w.verdict.verdict == "supported"
    assert [o.kind for o in w.ops] == ["add_edge", "verdict"]
    assert [o.seq for o in w.ops] == sorted(o.seq for o in w.ops)


def test_why_node_and_unknowns(built: tuple[Sample, FinalGraph]) -> None:
    s, fg = built
    w = why(fg.graph, fg.ops, s.p1)
    assert w.kind == "node"
    assert [o.kind for o in w.ops] == ["add_node", "add_unresolved", "add_flag"]
    term = why(fg.graph, fg.ops, s.term)
    assert term.statement == "unknown rule"
    with pytest.raises(KeyError):
        why(fg.graph, fg.ops, "p:nothing")
    with pytest.raises(KeyError):
        why(fg.graph, fg.ops, f"{s.p1}#permission")
    with pytest.raises(KeyError):
        why(fg.graph, fg.ops, f"{s.p1}#not_a_role")


def test_document_label_and_untitled() -> None:
    s = sample()
    s.draft.node(s.doc).label = "Custom"
    g = run(s).graph
    assert by_id(g, s.doc).label == "Custom"
    assert g.document.title == "Fee Schedule"
    assert by_id(g, s.doc).kind is NodeKind.DOCUMENT
