"""Spec 05 § 3 A-verify (T-AG-10)."""

from __future__ import annotations

import json

from agent_drafts import deps, draft
from fake_llm import CountingBudget, Reply, ScriptedModel

from inkthread.agents.verify import verify_agent
from inkthread.core.config import LlmMode
from inkthread.domain.draft import EdgeDraft, GraphDraft, RoleDraft
from inkthread.domain.model import Actor, Basis, EdgeType, FlagCode, Maker, NodeKind, Role, Span
from inkthread.llm.ports import ModelRequest

A = "Our results show that late filers pay more than twice the fee on average."
B = "Late filing is anything received after the thirtieth day of the quarter."
C = "If a filing is late, the surcharge applies to that member for the quarter."
KEY = "k" * 64


def agent(model: str, task: str = "A-classify") -> Maker:
    return Maker(actor=Actor.AGENT, id=task, model=model, request_key=KEY)


def setup(edge_model: str = "p/primary:free", role_model: str = "p/primary:free") -> GraphDraft:
    d = draft(
        ("p:1", NodeKind.PARAGRAPH, A),
        ("p:2", NodeKind.PARAGRAPH, B),
        ("p:3", NodeKind.PARAGRAPH, C),
    )
    d.add_role(
        "p:1",
        RoleDraft(
            role=Role.CLAIM,
            evidence=Span.of(A, 0, 11),
            made_by=agent(role_model),
            basis=Basis.SEMANTIC,
        ),
        stage="classify_agent",
    )
    d.add_role(
        "p:2",
        RoleDraft(
            role=Role.DEFINITION,
            evidence=None,
            made_by=Maker(actor=Actor.RULE, id="R-ROLE-definition"),
            basis=Basis.EXPLICIT,
        ),
        stage="classify_rules",
    )
    d.add_edge(
        EdgeDraft(
            type=EdgeType.QUALIFIES,
            source="p:3",
            target="p:1",
            basis=Basis.SEMANTIC,
            method="A-relate",
            made_by=agent(edge_model, "A-relate"),
            evidence=Span.of(C, 0, 20),
        ),
        stage="relate_agent",
    )
    return d


def claims(req: ModelRequest) -> list[dict[str, str]]:
    data: dict[str, list[dict[str, str]]] = json.loads(req.messages[1].content.partition("\n")[2])
    return data["claims"]


def verdicts(*pairs: tuple[str, str], served: str = "v/fast:free") -> Reply:
    return Reply(json.dumps({"verdicts": [{"claim": c, "verdict": v} for c, v in pairs]}), served)


async def test_claims_are_edges_then_semantic_roles() -> None:
    d = setup()
    model = ScriptedModel([verdicts()])
    await verify_agent(d, deps(model))
    sent = claims(model.requests[0])
    assert [c["kind"] for c in sent] == ["edge", "role"]
    assert sent[0] == {
        "id": "k1",
        "kind": "edge",
        "type": "qualifies",
        "source_text": C,
        "target_text": A,
        "quote": C[:20],
    }
    assert sent[1] == {"id": "k2", "kind": "role", "role": "claim", "part_text": A, "quote": A[:11]}
    assert model.requests[0].cascade == ("v/fast:free", "f/fallback:free")


async def test_verdicts_map_omitted_abstain_unsupported_contested() -> None:  # T-AG-10
    d = setup()
    report = await verify_agent(d, deps(ScriptedModel([verdicts(("k1", "unsupported"))])))
    (edge,) = d.edges.values()
    assert edge.verdict is not None
    assert edge.verdict.verdict == "unsupported"
    assert edge.verdict.model == "v/fast:free"
    assert any(f.code is FlagCode.CONTESTED for f in edge.flags)
    role = d.node("p:1").roles[Role.CLAIM]
    assert role.verdict is not None
    assert role.verdict.verdict == "abstain"
    assert d.node("p:2").roles[Role.DEFINITION].verdict is None
    verdict_ops = [o for o in d.ops if o.kind == "verdict"]
    assert {(o.actor, o.method) for o in verdict_ops} == {("verifier", "A-verify")}
    assert report.accepted == 2


async def test_role_unsupported_flags_the_node_contested() -> None:
    d = setup()
    await verify_agent(d, deps(ScriptedModel([verdicts(("k2", "unsupported"))])))
    assert d.node("p:1").has_flag(FlagCode.CONTESTED)


async def test_verdict_from_the_producing_model_is_discarded() -> None:  # T-AG-10
    d = setup(edge_model="f/fallback:free")
    report = await verify_agent(
        d,
        deps(
            ScriptedModel(
                [verdicts(("k1", "supported"), ("k2", "supported"), served="f/fallback:free")]
            )
        ),
    )
    (edge,) = d.edges.values()
    assert edge.verdict is None
    assert d.node("p:1").roles[Role.CLAIM].verdict is not None
    assert report.rejected == 1


async def test_unknown_claim_alias_is_ignored() -> None:
    d = setup()
    await verify_agent(d, deps(ScriptedModel([verdicts(("k9", "supported"))])))
    assert all(v is not None for v in [next(iter(d.edges.values())).verdict])


async def test_no_claims_no_call_and_budget_skip() -> None:
    d = draft(("p:1", NodeKind.PARAGRAPH, A))
    model = ScriptedModel([])
    report = await verify_agent(d, deps(model))
    assert (model.requests, report.calls) == ([], 0)
    d = setup()
    report = await verify_agent(d, deps(ScriptedModel([], budget=CountingBudget(limit=0))))
    assert report.skipped_reason == "budget"
    assert next(iter(d.edges.values())).verdict is None


async def test_off_mode_skips() -> None:
    d = setup()
    report = await verify_agent(d, deps(ScriptedModel([]), mode=LlmMode.OFF))
    assert report.skipped_reason == "disabled"
