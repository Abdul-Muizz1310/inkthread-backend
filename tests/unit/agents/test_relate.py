"""Spec 05 § 3 A-relate (T-AG-9)."""

from __future__ import annotations

import json

from agent_drafts import deps, draft, rule_role
from fake_llm import Reply, ScriptedModel

from inkthread.agents.relate import relate_agent
from inkthread.domain.draft import EdgeDraft, GraphDraft
from inkthread.domain.model import Actor, Basis, EdgeType, Maker, NodeKind, Role
from inkthread.llm.ports import ModelRequest

COND = "If the member files late, the surcharge in the table below applies to it."
EXC = "Except for new members, the fee is charged in full from the first month."
BASE = "The annual fee is charged to every member of the exchange each year."
TABLE = "Tier Fee 1 $10 2 $20"
FAR = "Members may contact the exchange office for any questions about fees."


def payload(req: ModelRequest) -> dict[str, list[dict[str, object]]]:
    data: dict[str, list[dict[str, object]]] = json.loads(
        req.messages[1].content.partition("\n")[2]
    )
    return data


def relations(*rels: dict[str, str]) -> Reply:
    return Reply(json.dumps({"relations": list(rels)}))


def setup() -> GraphDraft:
    d = draft(
        ("p:1", NodeKind.PARAGRAPH, BASE),
        ("p:2", NodeKind.PARAGRAPH, COND),
        ("p:3", NodeKind.TABLE, TABLE),
        ("p:4", NodeKind.PARAGRAPH, EXC),
        ("p:5", NodeKind.PARAGRAPH, FAR),
    )
    rule_role(d, "p:2", Role.CONDITION, "If", weak=True)
    rule_role(d, "p:4", Role.EXCEPTION, "Except")
    return d


async def offered(d: GraphDraft) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Run once with an empty answer: alias by node text, and each focus alias's candidates."""
    model = ScriptedModel([relations()])
    await relate_agent(d, deps(model))
    data = payload(model.requests[0])
    alias = {str(n["text"]): str(n["id"]) for n in data["nodes"]}
    cands = {str(f["id"]): [str(c) for c in f["candidates"]] for f in data["focus"]}  # type: ignore[union-attr]
    return alias, cands


async def test_focus_order_candidates_and_allowed_types() -> None:
    d = setup()
    model = ScriptedModel([relations()])
    await relate_agent(d, deps(model))
    data = payload(model.requests[0])
    text = {n["id"]: n["text"] for n in data["nodes"]}
    focus = data["focus"]
    assert [text[f["id"]] for f in focus] == [EXC, COND]  # strong cue first
    assert focus[0]["allowed"] == ["qualifies", "overrides"]
    assert focus[1]["allowed"] == ["qualifies"]
    cond_cands = [text[c] for c in focus[1]["candidates"]]  # type: ignore[union-attr]
    assert cond_cands[0] == TABLE  # tables first
    assert COND not in cond_cands
    assert all(len(str(t)) <= 400 for t in text.values())


async def test_no_focus_means_no_call() -> None:
    d = draft(("p:1", NodeKind.PARAGRAPH, BASE))
    model = ScriptedModel([])
    report = await relate_agent(d, deps(model))
    assert model.requests == []
    assert report.calls == 0


async def test_good_relation_becomes_semantic_edge() -> None:
    alias, _ = await offered(setup())
    d = setup()
    rel = {
        "focus": alias[COND],
        "type": "qualifies",
        "target": alias[TABLE],
        "evidence": "the surcharge in the table below applies",
    }
    report = await relate_agent(d, deps(ScriptedModel([relations(rel, rel)])))
    assert report.accepted == 1
    assert [r.reason for r in d.rejected] == ["duplicate"]
    (edge,) = d.edges.values()
    assert (edge.type, edge.source, edge.target) == (EdgeType.QUALIFIES, "p:2", "p:3")
    assert edge.basis is Basis.SEMANTIC
    assert edge.method == "A-relate"
    assert edge.made_by.actor is Actor.AGENT
    assert edge.evidence is not None
    assert edge.evidence.fits(COND)


async def test_rejections() -> None:  # T-AG-9
    alias, cands = await offered(setup())
    f_cond, f_exc = alias[COND], alias[EXC]
    target = alias[TABLE]
    only_exc = [c for c in cands[f_exc] if c not in cands[f_cond] and c != f_cond]
    rels = [
        {"focus": "c99", "type": "qualifies", "target": target, "evidence": "If the member"},
        {"focus": f_cond, "type": "illustrates", "target": target, "evidence": "If the member"},
        {"focus": f_cond, "type": "qualifies", "target": target, "evidence": "not in the text"},
        {"focus": f_cond, "type": "qualifies", "target": target, "evidence": ""},
        {"focus": f_cond, "type": "qualifies", "target": f_cond, "evidence": "If the member"},
    ]
    rels += [
        {"focus": f_cond, "type": "qualifies", "target": c, "evidence": "If the member"}
        for c in only_exc[:1]
    ]
    d = setup()
    await relate_agent(d, deps(ScriptedModel([relations(*rels)])))
    expected = ["unknown_id", "type_not_allowed", "quote_not_found", "no_evidence", "self_loop"]
    assert [r.reason for r in d.rejected] == expected + ["unknown_id"] * len(only_exc[:1])
    assert d.edges == {}


async def test_parts_with_an_outgoing_logic_edge_are_not_in_focus() -> None:
    d = setup()
    d.add_edge(
        EdgeDraft(
            type=EdgeType.OVERRIDES,
            source="p:4",
            target="p:1",
            basis=Basis.EXPLICIT,
            method="R-LINK-x",
            made_by=Maker(actor=Actor.RULE, id="R-LINK-x"),
        ),
        stage="link",
    )
    model = ScriptedModel([relations()])
    await relate_agent(d, deps(model))
    data = payload(model.requests[0])
    text = {n["id"]: n["text"] for n in data["nodes"]}
    assert [text[f["id"]] for f in data["focus"]] == [COND]
