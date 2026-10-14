"""Reasons, tiers and scores (spec 06 § 1-2, spec 05 § 7).

A tier is set by the worst severity among an element's reasons; a score is reported for sorting and
never decides anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import assert_never

from inkthread.domain.draft import EdgeDraft, NodeDraft, RoleDraft
from inkthread.domain.model import (
    Actor,
    Confidence,
    FlagCode,
    Maker,
    Reason,
    ReasonCode,
    Severity,
    Tier,
    Verdict,
)

SEVERITY: Mapping[ReasonCode, Severity] = {
    ReasonCode.VERIFIED_TEXT: Severity.INFO,
    ReasonCode.TEXT_DEFECT: Severity.CRITICAL,
    ReasonCode.HIDDEN_TEXT: Severity.FLAG,
    ReasonCode.UNRESOLVED_PARTS: Severity.FLAG,
    ReasonCode.EXPLICIT_INKGRID: Severity.INFO,
    ReasonCode.EXPLICIT_RULE: Severity.INFO,
    ReasonCode.WEAK_RULE: Severity.FLAG,
    ReasonCode.SEMANTIC_AGENT: Severity.INFO,
    ReasonCode.VERIFIER_SUPPORTED: Severity.FLAG,
    ReasonCode.VERIFIER_ABSTAINED: Severity.DOUBT,
    ReasonCode.VERIFIER_UNAVAILABLE: Severity.DOUBT,
    ReasonCode.VERIFIER_REJECTED: Severity.CRITICAL,
    ReasonCode.TARGET_DEFECT: Severity.FLAG,
}

_RANK: Mapping[Severity, int] = {s: i for i, s in enumerate(Severity)}

SCORE_INKGRID = 0.98
SCORE_STRONG_RULE = 0.95
SCORE_WEAK_RULE = 0.70
SCORE_AGENT_SUPPORTED = 0.75
SCORE_AGENT_NO_VERDICT = 0.55
SCORE_AGENT_REJECTED = 0.25
CAP_TARGET_DEFECT = 0.5
CAP_UNRESOLVED = 0.8
CAP_HIDDEN = 0.7
SCORE_TEXT_DEFECT = 0.2


def reason(code: ReasonCode, detail: str | None = None) -> Reason:
    """A reason with the severity spec 06 § 1 fixes for its code."""
    return Reason(code=code, severity=SEVERITY[code], detail=detail)


def _tier_of_severity(severity: Severity) -> Tier:
    match severity:
        case Severity.INFO | Severity.ADVICE:
            return Tier.A
        case Severity.FLAG:
            return Tier.B
        case Severity.DOUBT:
            return Tier.C
        case Severity.CRITICAL:
            return Tier.D
        case _:
            assert_never(severity)


def tier_of(reasons: Iterable[Reason]) -> Tier:
    """The tier set by the worst severity; no reasons gives A."""
    worst = max((r.severity for r in reasons), key=_RANK.__getitem__, default=Severity.INFO)
    return _tier_of_severity(worst)


def _confidence(reasons: list[Reason], score: float) -> Confidence:
    return Confidence(tier=tier_of(reasons), score=score, reasons=tuple(reasons))


def score_node(node: NodeDraft, *, verified: bool) -> Confidence:
    """A node's confidence from its flags, its unresolved entries and the reading's verification."""
    reasons: list[Reason] = []
    score = 1.0
    defect = node.has_flag(FlagCode.TEXT_DEFECT)
    if verified and not defect:
        reasons.append(reason(ReasonCode.VERIFIED_TEXT))
    if node.unresolved:
        reasons.append(reason(ReasonCode.UNRESOLVED_PARTS))
        score = min(score, CAP_UNRESOLVED)
    if node.has_flag(FlagCode.HIDDEN_TEXT):
        reasons.append(reason(ReasonCode.HIDDEN_TEXT))
        score = min(score, CAP_HIDDEN)
    if defect:
        details = sorted({f.detail or "" for f in node.flags if f.code is FlagCode.TEXT_DEFECT})
        reasons.append(reason(ReasonCode.TEXT_DEFECT, "; ".join(d for d in details if d) or None))
        score = SCORE_TEXT_DEFECT
    return _confidence(reasons, score)


def _verdict_reason(verdict: Verdict | None) -> tuple[ReasonCode, float]:
    if verdict is None:
        return ReasonCode.VERIFIER_UNAVAILABLE, SCORE_AGENT_NO_VERDICT
    match verdict.verdict:
        case "supported":
            return ReasonCode.VERIFIER_SUPPORTED, SCORE_AGENT_SUPPORTED
        case "abstain":
            return ReasonCode.VERIFIER_ABSTAINED, SCORE_AGENT_NO_VERDICT
        case "unsupported":
            return ReasonCode.VERIFIER_REJECTED, SCORE_AGENT_REJECTED
        case _:
            assert_never(verdict.verdict)


def _claim(maker: Maker, *, weak: bool, verdict: Verdict | None) -> tuple[list[Reason], float]:
    match maker.actor:
        case Actor.INKGRID:
            return [reason(ReasonCode.EXPLICIT_INKGRID)], SCORE_INKGRID
        case Actor.RULE:
            if weak:
                return [reason(ReasonCode.WEAK_RULE)], SCORE_WEAK_RULE
            return [reason(ReasonCode.EXPLICIT_RULE)], SCORE_STRONG_RULE
        case Actor.AGENT:
            code, score = _verdict_reason(verdict)
            return [reason(ReasonCode.SEMANTIC_AGENT), reason(code)], score
        case Actor.VERIFIER:
            msg = f"a verifier judges claims; it does not make them ({maker.id})"
            raise ValueError(msg)
        case _:
            assert_never(maker.actor)


def score_role(role: RoleDraft) -> Confidence:
    """A role's confidence from its maker, its cue strength and the verifier's verdict."""
    reasons, score = _claim(role.made_by, weak=role.weak, verdict=role.verdict)
    return _confidence(reasons, score)


def score_edge(edge: EdgeDraft, target: NodeDraft) -> Confidence:
    """An edge's confidence; an edge into a defective node also gets `target_defect`."""
    reasons, score = _claim(edge.made_by, weak=edge.weak, verdict=edge.verdict)
    if target.has_flag(FlagCode.TEXT_DEFECT):
        reasons.append(reason(ReasonCode.TARGET_DEFECT, target.id))
        score = min(score, CAP_TARGET_DEFECT)
    return _confidence(reasons, score)
