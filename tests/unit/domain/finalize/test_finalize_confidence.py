"""Spec 06 § 1-2 and spec 05 § 7: reasons, tiers and scores (T-CP-1…3)."""

from __future__ import annotations

import pytest

from inkthread.domain.confidence import SEVERITY, score_edge, score_node, score_role, tier_of
from inkthread.domain.draft import EdgeDraft, NodeDraft, RoleDraft
from inkthread.domain.model import (
    Actor,
    Basis,
    EdgeType,
    Flag,
    FlagCode,
    Maker,
    NodeKind,
    Reason,
    ReasonCode,
    Region,
    Role,
    Severity,
    Span,
    Tier,
    Unresolved,
    Verdict,
)

RULE = Maker(actor=Actor.RULE, id="R-X")
INK = Maker(actor=Actor.INKGRID, id="inkgrid")
AGENT = Maker(actor=Actor.AGENT, id="A-relate", model="m/a", request_key="rk")

EXPECTED_TIER = {
    ReasonCode.VERIFIED_TEXT: Tier.A,
    ReasonCode.TEXT_DEFECT: Tier.D,
    ReasonCode.HIDDEN_TEXT: Tier.B,
    ReasonCode.UNRESOLVED_PARTS: Tier.B,
    ReasonCode.EXPLICIT_INKGRID: Tier.A,
    ReasonCode.EXPLICIT_RULE: Tier.A,
    ReasonCode.WEAK_RULE: Tier.B,
    ReasonCode.SEMANTIC_AGENT: Tier.A,
    ReasonCode.VERIFIER_SUPPORTED: Tier.B,
    ReasonCode.VERIFIER_ABSTAINED: Tier.C,
    ReasonCode.VERIFIER_UNAVAILABLE: Tier.C,
    ReasonCode.VERIFIER_REJECTED: Tier.D,
    ReasonCode.TARGET_DEFECT: Tier.B,
}


def r(code: ReasonCode) -> Reason:
    return Reason(code=code, severity=SEVERITY[code])


@pytest.mark.parametrize("code", list(ReasonCode))
def test_each_reason_maps_to_its_tier(code: ReasonCode) -> None:  # T-CP-1
    assert tier_of([r(code)]) is EXPECTED_TIER[code]


def test_tier_is_the_worst_severity() -> None:  # T-CP-1
    assert tier_of([]) is Tier.A
    assert tier_of([Reason(code=ReasonCode.VERIFIED_TEXT, severity=Severity.ADVICE)]) is Tier.A
    assert tier_of([r(ReasonCode.HIDDEN_TEXT), r(ReasonCode.VERIFIER_ABSTAINED)]) is Tier.C
    every = [r(c) for c in ReasonCode]
    assert tier_of(every) is Tier.D
    assert tier_of(list(reversed(every))) is Tier.D


def node(text: str = "Members must pay.", **extra: object) -> NodeDraft:
    return NodeDraft(
        id="p:1",
        kind=NodeKind.PARAGRAPH,
        text=text,
        order=1,
        section="d:x",
        depth=1,
        regions=[Region(page=1, bbox=(0, 0, 1, 1))],
        made_by=RULE,
        **extra,  # type: ignore[arg-type]
    )


def codes(conf_reasons: tuple[Reason, ...]) -> list[ReasonCode]:
    return [x.code for x in conf_reasons]


def test_clean_verified_node_is_a() -> None:
    c = score_node(node(), verified=True)
    assert (c.tier, c.score, codes(c.reasons)) == (Tier.A, 1.0, [ReasonCode.VERIFIED_TEXT])
    unverified = score_node(node(), verified=False)
    assert (unverified.tier, unverified.score, unverified.reasons) == (Tier.A, 1.0, ())


def test_hidden_and_unresolved_cap_the_score() -> None:
    n = node(
        flags=[Flag(code=FlagCode.HIDDEN_TEXT)],
        unresolved=[Unresolved(kind="note", text="2", reason="x")],
    )
    c = score_node(n, verified=True)
    assert c.tier is Tier.B
    assert c.score == pytest.approx(0.7)
    assert set(codes(c.reasons)) == {
        ReasonCode.VERIFIED_TEXT,
        ReasonCode.HIDDEN_TEXT,
        ReasonCode.UNRESOLVED_PARTS,
    }
    only_unresolved = node(unresolved=[Unresolved(kind="note", text="2", reason="x")])
    assert score_node(only_unresolved, verified=True).score == pytest.approx(0.8)


def test_text_defect_node_and_edges_into_it() -> None:  # T-CP-2
    bad = node(flags=[Flag(code=FlagCode.TEXT_DEFECT, detail="garbled")])
    c = score_node(bad, verified=True)
    assert (c.tier, c.score) == (Tier.D, 0.2)
    assert ReasonCode.VERIFIED_TEXT not in codes(c.reasons)
    assert ReasonCode.TEXT_DEFECT in codes(c.reasons)
    e = EdgeDraft(
        type=EdgeType.REFERS_TO,
        source="p:0",
        target="p:1",
        basis=Basis.EXPLICIT,
        method="R-X",
        made_by=RULE,
    )
    ce = score_edge(e, bad)
    assert ReasonCode.TARGET_DEFECT in codes(ce.reasons)
    assert ce.score <= 0.5
    assert ce.tier is Tier.B
    assert ReasonCode.TARGET_DEFECT not in codes(score_edge(e, node()).reasons)


def edge(maker: Maker, *, weak: bool = False, verdict: Verdict | None = None) -> EdgeDraft:
    return EdgeDraft(
        type=EdgeType.QUALIFIES,
        source="p:0",
        target="p:1",
        basis=Basis.SEMANTIC if maker.actor is Actor.AGENT else Basis.EXPLICIT,
        method=maker.id,
        made_by=maker,
        weak=weak,
        verdict=verdict,
    )


def test_explicit_makers() -> None:
    target = node()
    ink = score_edge(edge(INK), target)
    assert (ink.tier, ink.score, codes(ink.reasons)) == (
        Tier.A,
        0.98,
        [ReasonCode.EXPLICIT_INKGRID],
    )
    strong = score_edge(edge(RULE), target)
    assert (strong.tier, strong.score, codes(strong.reasons)) == (
        Tier.A,
        0.95,
        [ReasonCode.EXPLICIT_RULE],
    )
    weak = score_edge(edge(RULE, weak=True), target)
    assert (weak.tier, weak.score, codes(weak.reasons)) == (Tier.B, 0.70, [ReasonCode.WEAK_RULE])
    role = score_role(
        RoleDraft(role=Role.OBLIGATION, evidence=None, made_by=RULE, basis=Basis.EXPLICIT)
    )
    assert (role.tier, role.score, codes(role.reasons)) == (
        Tier.A,
        0.95,
        [ReasonCode.EXPLICIT_RULE],
    )
    weak_role = score_role(
        RoleDraft(role=Role.SCOPE, evidence=None, made_by=RULE, basis=Basis.EXPLICIT, weak=True)
    )
    assert (weak_role.tier, weak_role.score) == (Tier.B, 0.70)


def verdict(v: str) -> Verdict:
    return Verdict(verdict=v, model="m/v", request_key="rk-v")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("given", "second", "tier", "score"),
    [
        (verdict("supported"), ReasonCode.VERIFIER_SUPPORTED, Tier.B, 0.75),
        (None, ReasonCode.VERIFIER_UNAVAILABLE, Tier.C, 0.55),
        (verdict("abstain"), ReasonCode.VERIFIER_ABSTAINED, Tier.C, 0.55),
        (verdict("unsupported"), ReasonCode.VERIFIER_REJECTED, Tier.D, 0.25),
    ],
)
def test_agent_claim_states(
    given: Verdict | None, second: ReasonCode, tier: Tier, score: float
) -> None:  # T-CP-3
    for conf in (
        score_edge(edge(AGENT, verdict=given), node()),
        score_role(
            RoleDraft(
                role=Role.EXAMPLE,
                evidence=Span.of("an example", 0, 2),
                made_by=AGENT,
                basis=Basis.SEMANTIC,
                verdict=given,
            )
        ),
    ):
        assert codes(conf.reasons) == [ReasonCode.SEMANTIC_AGENT, second]
        assert conf.tier is tier
        assert conf.score == pytest.approx(score)
