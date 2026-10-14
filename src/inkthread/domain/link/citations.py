"""Citations to outside sources (spec 04 § 4), shared with spec 03's `R-ROLE-external_pointer`."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from inkthread.domain.draft import EdgeDraft, GraphDraft
from inkthread.domain.ids import external_id, fold
from inkthread.domain.link.nodes import STAGE, add_unplaced, content_nodes, rule
from inkthread.domain.link.refsyntax import REF_LIST
from inkthread.domain.model import Basis, EdgeType, NodeKind, Span

_SECTION = r"(?:\s*§+\s*|\s+Part\s+|\s+)"
_CFR = re.compile(
    rf"(?<!\w)(?P<title>\d+)\s+C\.?\s?F\.?\s?R\.?{_SECTION}"
    r"(?P<sec>\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*)(?![\w.]\d)"
)
_USC = re.compile(
    r"(?<!\w)(?P<title>\d+)\s+U\.?\s?S\.?\s?C\.?(?:\s*§+\s*|\s+)"
    r"(?P<sec>\d+[a-z]*(?:-\d+)?(?:\([A-Za-z0-9]+\))*)(?![\w.]\d)"
)
_EU = re.compile(
    r"(?<!\w)(?:Regulation|Directive|Decision)\s+"
    r"(?:\((?:EU|EC|EEC|Euratom)\)\s+(?:No\.?\s*)?\d+/\d+|(?:No\.?\s*)?\d{2,4}/\d+/(?:EU|EC|EEC))"
    r"(?!\w)"
)
_PUBLAW = re.compile(r"(?<!\w)(?:Pub\.\s*L\.|Public\s+Law)\s*(?:No\.\s*)?(?P<num>\d+-\d+)(?!\w)")
_ACT = re.compile(
    r"(?<!\w)(?P<the>[Tt]he\s+)?(?P<name>(?:[A-Z][\w'\u2019.&-]*\s+){1,8})Act(?!\w)"
    r"(?:\s+of\s+\d{4}(?!\w))?"
)
_DETERMINERS = frozenset({"This", "That", "Such", "Said", "The", "Each", "Any", "An", "A"})
_NAMED = re.compile(
    r"(?<!\w)of\s+the\s+(?P<name>(?:[A-Z][\w.'\u2019&-]*\s+){0,7}"
    r"(?:Rules|Rulebook|Code|Regulations?|Directive|By-[Ll]aws|Agreement|Handbook|Guide"
    r"|Manual|Standard|Policy))(?!\w)"
)
_STANDARD = re.compile(
    r"(?<!\w)(?:ISO(?:/IEC)?\s+\d+(?:-\d+)*(?::\d{4})?"
    r"|NIST\s+(?:SP|AI|IR)\s+\d+(?:-\d+)*[A-Za-z]?"
    r"|FIPS\s+(?:PUB\s+)?\d+(?:-\d+)?"
    r"|RFC\s+\d+"
    r"|IEEE\s+(?:Std\s+)?\d+(?:\.\d+)*(?:-\d{4})?)(?!\w)"
)
_URL = re.compile(
    r"(?<![\w/:.])(?:https?://|doi:\s*10\.\d{4,9}/|10\.\d{4,9}/)[^\s<>\"“”]+",
    re.IGNORECASE,
)
_URL_TAIL = ".,;:!?)]}'\"\u2019/"
_QUALIFIER = re.compile(r"\s+(?:of|in|under)\s+(?P<the>the\s+)?", re.IGNORECASE)


@dataclass(frozen=True)
class CitationHit:
    """One citation: where it is printed, its normalised key, and the rule that matched it."""

    span: Span
    key: str
    rule: str


def _key(text: str) -> str:
    return fold(text).lower()


def _cfr(text: str, m: re.Match[str]) -> CitationHit:
    key = f"{m.group('title')} cfr {m.group('sec')}".lower()
    return CitationHit(Span.of(text, m.start(), m.end()), key, "R-CITE-cfr")


def _usc(text: str, m: re.Match[str]) -> CitationHit:
    key = f"{m.group('title')} usc {m.group('sec')}".lower()
    return CitationHit(Span.of(text, m.start(), m.end()), key, "R-CITE-usc")


def _eu(text: str, m: re.Match[str]) -> CitationHit:
    return CitationHit(Span.of(text, m.start(), m.end()), _key(m.group()), "R-CITE-eu")


def _publaw(text: str, m: re.Match[str]) -> CitationHit:
    key = f"public law {m.group('num')}"
    return CitationHit(Span.of(text, m.start(), m.end()), key, "R-CITE-publaw")


def _act(text: str, m: re.Match[str]) -> CitationHit | None:
    words = m.group("name").split()
    cut = max((i + 1 for i, w in enumerate(words) if w in _DETERMINERS), default=0)
    if cut >= len(words):
        return None
    start = m.start() if cut == 0 else m.start("name") + m.group("name").index(words[cut])
    span = Span.of(text, start, m.end())
    key = _key(span.quote)
    key = key.removeprefix("the ")
    return CitationHit(span, key, "R-CITE-act")


def _named(text: str, m: re.Match[str]) -> CitationHit:
    span = Span.of(text, m.start("name"), m.end("name"))
    return CitationHit(span, _key(span.quote), "R-CITE-named")


def _standard(text: str, m: re.Match[str]) -> CitationHit:
    return CitationHit(Span.of(text, m.start(), m.end()), _key(m.group()), "R-CITE-standard")


def _url(text: str, m: re.Match[str]) -> CitationHit | None:
    end = m.end()
    while end > m.start() and text[end - 1] in _URL_TAIL:
        end -= 1
    if end <= m.start() or text[end - 1] == "/":
        return None
    span = Span.of(text, m.start(), end)
    return CitationHit(span, span.quote.lower(), "R-CITE-url")


_Builder = Callable[[str, re.Match[str]], CitationHit | None]
_RULES: tuple[tuple[re.Pattern[str], _Builder], ...] = (
    (_CFR, _cfr),
    (_USC, _usc),
    (_EU, _eu),
    (_PUBLAW, _publaw),
    (_ACT, _act),
    (_NAMED, _named),
    (_STANDARD, _standard),
    (_URL, _url),
)


def find_citations(text: str) -> list[CitationHit]:
    """Every citation in the text, in reading order; overlapping matches keep the longest."""
    candidates = [
        hit
        for pattern, build in _RULES
        for m in pattern.finditer(text)
        if (hit := build(text, m)) is not None
    ]
    candidates.sort(key=lambda h: (h.span.start - h.span.end, h.span.start))
    kept: list[CitationHit] = []
    for hit in candidates:
        if any(hit.span.start < k.span.end and k.span.start < hit.span.end for k in kept):
            continue
        kept.append(hit)
    return sorted(kept, key=lambda h: h.span.start)


@dataclass(frozen=True)
class QualifiedRef:
    """A section reference into an outside source: `Section 10(b) of the … Act`."""

    start: int
    refs_end: int
    citation: CitationHit


def qualified_refs(text: str, hits: list[CitationHit]) -> list[QualifiedRef]:
    """Reference lists followed, in the same breath, by `of`/`in`/`under` and a citation."""
    by_start = {h.span.start: h for h in hits}
    found: list[QualifiedRef] = []
    for m in REF_LIST.finditer(text):
        q = _QUALIFIER.match(text, m.end())
        if q is None:
            continue
        hit = by_start.get(q.end())
        if hit is None and q.group("the") is not None:
            hit = by_start.get(q.start("the"))
        if hit is not None:
            found.append(QualifiedRef(start=m.start(), refs_end=m.end(), citation=hit))
    return found


def _self_keys(draft: GraphDraft) -> set[str]:
    keys: set[str] = set()
    for doc in draft.nodes_of(NodeKind.DOCUMENT):
        if doc.label:
            title = _key(doc.label)
            keys |= {title, title.removeprefix("the ")}
    return keys


def link_citations(draft: GraphDraft) -> None:
    """Add external nodes and `cites_external` edges for every citation in every part."""
    own = _self_keys(draft)
    for node in content_nodes(draft):
        hits = [h for h in find_citations(node.text) if h.key not in own]
        phrases = {q.citation.span.start: q.start for q in qualified_refs(node.text, hits)}
        for hit in hits:
            xid = external_id(hit.key)
            add_unplaced(draft, xid, NodeKind.EXTERNAL, hit.span.quote, rule(hit.rule))
            start = phrases.get(hit.span.start, hit.span.start)
            evidence = Span.of(node.text, start, hit.span.end)
            draft.add_edge(
                EdgeDraft(
                    type=EdgeType.CITES_EXTERNAL,
                    source=node.id,
                    target=xid,
                    basis=Basis.EXPLICIT,
                    method=hit.rule,
                    made_by=rule(hit.rule),
                    evidence=evidence,
                    label=evidence.quote,
                ),
                stage=STAGE,
            )
