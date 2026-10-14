"""Precedence language: `overrides` and `qualifies` (spec 04 § 7)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from inkthread.domain.draft import EdgeDraft, GraphDraft
from inkthread.domain.link.nodes import STAGE, rule
from inkthread.domain.link.references import CAPTION_RULE, SECTION_RULE, ResolvedRef
from inkthread.domain.model import Basis, EdgeType, EvidenceSide, Span
from inkthread.domain.text import sentence_at


@dataclass(frozen=True)
class _Cue:
    rule: str
    pattern: re.Pattern[str]
    edge: EdgeType
    toward_ref: bool  # True: this → T, evidence on source; False: T → this, evidence on target


def _w(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", re.IGNORECASE)


_CUES = (
    _Cue("R-PREC-notwithstanding", _w(r"notwithstanding"), EdgeType.OVERRIDES, toward_ref=True),
    _Cue(
        "R-PREC-supersedes",
        _w(
            r"supersedes|replaces|in\s+lieu\s+of|in\s+place\s+of|takes\s+precedence\s+over"
            r"|prevails\s+over|overrides"
        ),
        EdgeType.OVERRIDES,
        toward_ref=True,
    ),
    _Cue(
        "R-PREC-except-as",
        _w(
            r"except\s+as\s+(?:otherwise\s+)?(?:provided|set\s+out|set\s+forth|stated|specified"
            r"|described)\s+(?:in|by|under)"
        ),
        EdgeType.OVERRIDES,
        toward_ref=False,
    ),
    _Cue(
        "R-PREC-unless-otherwise",
        _w(r"unless\s+otherwise\s+(?:provided|stated|specified)\s+(?:in|by|under)"),
        EdgeType.OVERRIDES,
        toward_ref=False,
    ),
    _Cue("R-PREC-subject-to", _w(r"subject\s+to"), EdgeType.QUALIFIES, toward_ref=False),
)
_LEAD_GAP = re.compile(r"^[^,;:()]{0,40}$")
_CHAIN_GAP = re.compile(
    r"^(?:\s|,|and|or|to|through|-|\u2013|§|sections?|clauses?|articles?)*$", re.IGNORECASE
)
_TARGET_RULES = frozenset({SECTION_RULE, CAPTION_RULE})


def _governed(
    text: str, start: int, end: int, refs: list[ResolvedRef], taken: set[ResolvedRef]
) -> list[ResolvedRef]:
    """The reference list a cue at [start, end) introduces, within its sentence."""
    _, stop = sentence_at(text, start)
    after = [r for r in refs if end <= r.span.start and r.span.end <= stop and r not in taken]
    if not after or not _LEAD_GAP.match(text[end : after[0].span.start]):
        return []
    chain = [after[0]]
    for ref in after[1:]:
        last = chain[-1].span.end
        if ref.span.start < last or _CHAIN_GAP.match(text[last : ref.span.start]):
            chain.append(ref)
        else:
            break
    return chain


def link_precedence(draft: GraphDraft, refs: list[ResolvedRef]) -> set[ResolvedRef]:
    """Add precedence edges; return the references they consumed."""
    consumed: set[ResolvedRef] = set()
    by_node: dict[str, list[ResolvedRef]] = {}
    for ref in refs:
        if ref.rule in _TARGET_RULES:
            by_node.setdefault(ref.node, []).append(ref)
    for node_id, node_refs in by_node.items():
        text = draft.node(node_id).text
        ordered = sorted(node_refs, key=lambda r: (r.span.start, r.span.end))
        hits = sorted(
            ((m, cue) for cue in _CUES for m in cue.pattern.finditer(text)),
            key=lambda pair: pair[0].start(),
        )
        for m, cue in hits:
            for ref in _governed(text, m.start(), m.end(), ordered, consumed):
                consumed.add(ref)
                evidence = Span.of(text, m.start(), ref.span.end)
                source, target = (node_id, ref.target) if cue.toward_ref else (ref.target, node_id)
                draft.add_edge(
                    EdgeDraft(
                        type=cue.edge,
                        source=source,
                        target=target,
                        basis=Basis.EXPLICIT,
                        method=cue.rule,
                        made_by=rule(cue.rule),
                        evidence=evidence,
                        evidence_on=EvidenceSide.SOURCE if cue.toward_ref else EvidenceSide.TARGET,
                        label=ref.label,
                    ),
                    stage=STAGE,
                )
    return consumed
