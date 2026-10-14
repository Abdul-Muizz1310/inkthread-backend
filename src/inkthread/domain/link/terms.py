"""Term nodes and their `defines` and `uses_term` edges (spec 04 § 3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from inkthread.domain.draft import EdgeDraft, GraphDraft, NodeDraft
from inkthread.domain.ids import fold, term_id
from inkthread.domain.link.definitions import DefinitionHit, find_definitions, infer_glossary_term
from inkthread.domain.link.nodes import STAGE, add_unplaced, content_nodes, rule
from inkthread.domain.model import Basis, EdgeType, Flag, FlagCode, NodeKind, Span

USE_RULE = "R-TERM-use"
_SUFFIX = r"(?:s|es|['\u2019]s)?"


def term_key(term: str) -> str:
    """A multi-word term keys casefolded and whitespace-folded; one word keys as printed."""
    folded = fold(term)
    return folded.casefold() if " " in folded else folded


def _phrase(term: str) -> tuple[str, int]:
    """The regex for one printed form and its flags."""
    words = term.split()
    stem = r"\s+".join(re.escape(w) for w in words)
    alternatives = [stem + _SUFFIX]
    last = words[-1]
    if len(last) > 1 and last[-1] in "yY" and last[-2].lower() not in "aeiou":
        head = r"\s+".join(re.escape(w) for w in [*words[:-1], last[:-1]])
        alternatives.append(head + "ies")
    flags = re.IGNORECASE if len(words) > 1 else 0
    return "|".join(alternatives), flags


@dataclass(frozen=True)
class TermForms:
    """Every printed form that counts as a use of one term."""

    key: str
    patterns: tuple[re.Pattern[str], ...]
    length: int

    @classmethod
    def of(cls, term: str, aliases: tuple[str, ...] = ()) -> TermForms:
        """The forms of a term and of its aliases (an acronym's long form)."""
        compiled = []
        for form in (term, *aliases):
            body, flags = _phrase(form)
            compiled.append(re.compile(rf"(?<![\w]){body}(?![\w])", flags))
        return cls(key=term_key(term), patterns=tuple(compiled), length=len(term))


@dataclass(frozen=True)
class TermUse:
    """One claimed occurrence of a term in a text."""

    key: str
    span: Span


def match_terms(text: str, forms: list[TermForms]) -> list[TermUse]:
    """Every term occurrence, longest first, so no character is claimed twice; in text order."""
    candidates = [
        (m.start(), m.end(), f.key)
        for f in forms
        for pattern in f.patterns
        for m in pattern.finditer(text)
    ]
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    claimed: list[tuple[int, int]] = []
    uses: list[TermUse] = []
    for start, end, key in candidates:
        if any(start < e and s < end for s, e in claimed):
            continue
        claimed.append((start, end))
        uses.append(TermUse(key=key, span=Span.of(text, start, end)))
    return sorted(uses, key=lambda u: u.span.start)


@dataclass
class _Term:
    printed: str
    rule: str
    definers: dict[str, DefinitionHit] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)


def node_definitions(node: NodeDraft) -> list[DefinitionHit]:
    """The definitions a node states; a glossary block's term comes first."""
    block_term = infer_glossary_term(node.text) if node.kind is NodeKind.DEFINITION else None
    return find_definitions(node.text, block_term=block_term)


def _collect(draft: GraphDraft) -> dict[str, _Term]:
    terms: dict[str, _Term] = {}
    for node in content_nodes(draft):
        if node.kind is NodeKind.TABLE:
            continue
        for hit in node_definitions(node):
            key = term_key(hit.term.quote)
            entry = terms.setdefault(key, _Term(printed=hit.term.quote, rule=hit.rule))
            entry.definers.setdefault(node.id, hit)
            if hit.alias is not None and hit.alias.quote not in entry.aliases:
                entry.aliases.append(hit.alias.quote)
    return terms


def link_terms(draft: GraphDraft) -> None:
    """Add term nodes, `defines` edges, `multiple_definitions` flags and `uses_term` edges."""
    terms = _collect(draft)
    ids: dict[str, str] = {}
    for key, entry in terms.items():
        tid = term_id(key)
        ids[key] = tid
        add_unplaced(draft, tid, NodeKind.TERM, entry.printed, rule(entry.rule))
        for node_id, hit in entry.definers.items():
            draft.add_edge(
                EdgeDraft(
                    type=EdgeType.DEFINES,
                    source=node_id,
                    target=tid,
                    basis=Basis.EXPLICIT,
                    method=hit.rule,
                    made_by=rule(hit.rule),
                    evidence=hit.term,
                    label=hit.term.quote,
                ),
                stage=STAGE,
            )
        if len(entry.definers) > 1:
            flag = Flag(code=FlagCode.MULTIPLE_DEFINITIONS, detail=str(len(entry.definers)))
            draft.add_flag(tid, flag, stage=STAGE, maker=rule(entry.rule))
    forms = [TermForms.of(e.printed, tuple(e.aliases)) for e in terms.values()]
    for node in content_nodes(draft):
        _link_uses(draft, node, forms, terms, ids)


def _link_uses(
    draft: GraphDraft,
    node: NodeDraft,
    forms: list[TermForms],
    terms: dict[str, _Term],
    ids: dict[str, str],
) -> None:
    seen: set[str] = set()
    for use in match_terms(node.text, forms):
        if use.key in seen or node.id in terms[use.key].definers:
            continue
        seen.add(use.key)
        draft.add_edge(
            EdgeDraft(
                type=EdgeType.USES_TERM,
                source=node.id,
                target=ids[use.key],
                basis=Basis.EXPLICIT,
                method=USE_RULE,
                made_by=rule(USE_RULE),
                evidence=use.span,
                label=use.span.quote,
            ),
            stage=STAGE,
        )
