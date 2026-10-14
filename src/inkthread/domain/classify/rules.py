"""Rule-made roles (spec 03 § 2): one function per role, each returning the cue that fired."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from inkthread.domain.draft import GraphDraft, NodeDraft, RoleDraft
from inkthread.domain.link.citations import find_citations
from inkthread.domain.link.definitions import find_definitions, infer_glossary_term
from inkthread.domain.link.identifiers import cell_spans
from inkthread.domain.model import Actor, Basis, Maker, NodeKind, Role, Span

STAGE = "classify_rules"
TEXT_KINDS = frozenset({NodeKind.PARAGRAPH, NodeKind.LIST_ITEM, NodeKind.NOTE, NodeKind.DEFINITION})
TABLE_ROLES = (Role.TEMPORAL, Role.QUANTITATIVE)


@dataclass(frozen=True)
class Match:
    """The cue that fired a role rule; `weak` when only a weak cue fired."""

    span: Span | None
    weak: bool = False


def _w(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", flags)


def _first(text: str, *patterns: re.Pattern[str], weak: bool = False) -> Match | None:
    found = [m for p in patterns if (m := p.search(text)) is not None]
    if not found:
        return None
    m = min(found, key=lambda x: x.start())
    return Match(Span.of(text, m.start(), m.end()), weak)


_NUM = r"\d+(?:[.,]\d+)*"
_CURRENCY = r"[$€£¥]"
_ISO = r"USD|EUR|GBP|JPY|CHF|CAD|AUD|CNY|HKD|SGD|INR|NZD|SEK|NOK|DKK"
_MONTH = r"January|February|March|April|May|June|July|August|September|October|November|December"

_OBLIGATION = _w(
    r"(?:shall|must)(?!\s+(?:not|mean|means|include|includes|have\s+the\s+meaning)(?!\w))"
    r"|(?:is|are)\s+(?:required|obliged)\s+to|(?:has|have)\s+to|(?:is|are)\s+responsible\s+for"
)
_PROHIBITION = _w(
    r"(?:shall|must|may)\s+not|cannot|(?:is|are)\s+(?:prohibited|not\s+permitted|forbidden)"
)
_PERMISSION = _w(r"(?:is|are)\s+(?:permitted|entitled|allowed)\s+to")
_MAY = _w(
    r"may(?=\s+(?!(?:be|not|vary|differ|change|include|also|have|result|occur|apply)(?!\w))\w)"
)
_CONDITION = _w(
    r"provided\s+that|on\s+condition\s+that|subject\s+to|in\s+the\s+event\s+(?:of|that)"
    rf"|only\s+if|eligible|eligibility|qualify|qualifies|qualified|threshold"
    rf"|at\s+least\s+{_CURRENCY}?{_NUM}"
)
_IF = _w(r"if")
_EXCEPTION = _w(
    r"except|excluding|other\s+than|notwithstanding|save\s+(?:as|that|for)|unless"
    r"|(?:does|do|shall|will)\s+not\s+apply|(?:is|are)\s+exempt|exemption"
    r"|with\s+the\s+exception\s+of"
)
_COMPUTATION = _w(
    r"calculated|computed|calculation|multiplied\s+by|divided\s+by|the\s+(?:sum|total)\s+of"
    r"|the\s+(?:greater|lesser|higher|lower)\s+of|pro\s+rata|percent(?:age)?\s+of"
    r"|per\s+cent\s+of|formula|is\s+equal\s+to"
)
_METHOD = _w(
    r"measured|aggregated|averaged|average\s+daily"
    r"|on\s+an?\s+(?:daily|monthly|quarterly|annual)\s+basis|billing\s+period"
    r"|determined\s+(?:by|on|using)|methodology|is\s+assessed\s+(?:on|by)"
)
_STEPS = _w(r"step\s+\d+|the\s+following\s+steps")
_PROCEDURE_VERB = re.compile(
    r"^\s*(?P<verb>Submit|Complete|Enter|Select|Click|Open|Attach|File|Sign|Send|Provide"
    r"|Review|Ensure|Verify|Record|Notify)(?!\w)"
)
_LIST_LABEL = re.compile(r"^\(?(?:\d+|[A-Za-z]|[ivxlcdm]+|[IVXLCDM]+)[.)]?$")
_DATE = _w(
    rf"(?:{_MONTH})\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+(?:{_MONTH}),?\s+\d{{4}}"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}",
    0,
)
_TEMPORAL = _w(
    r"effective|expires?|no\s+later\s+than"
    r"|within\s+\d+\s+(?:business\s+)?(?:days?|months?|years?)|deadline|commencing"
)
_QUANTITATIVE = _w(
    rf"{_CURRENCY}\s?{_NUM}|(?:{_ISO})\s?{_NUM}|{_NUM}\s?(?:{_ISO})"
    rf"|{_NUM}\s?%|{_NUM}\s+(?:per\s+cent|percent)"
    rf"|{_NUM}\s?(?:bps?|basis\s+points?)"
    rf"|{_NUM}\s?(?:kg|mg|g|lbs?|km|cm|mm|ft|kWh|MWh|GWh|kW|MW|GB|MB|TB|KB|hours?|hrs?"
    r"|minutes?|mins?|seconds?|days?|weeks?|months?|years?|tonnes?|tons?|litres?|liters?"
    r"|gallons?|miles?)"
)
_PERCENT_SIGN = re.compile(rf"(?<!\w){_NUM}\s?%")
_NUMERIC_CELL = re.compile(rf"^\s*[-+(]?{_CURRENCY}?\d[\d,]*(?:\.\d+)?%?\)?\s*$")
_SCOPE = _w(
    r"(?:applies|apply|shall\s+apply)\s+to|applicable\s+to"
    r"|this\s+(?:section|part|chapter|schedule|document|policy|agreement|guide|standard)\s+"
    r"(?:applies|covers|governs|sets\s+out)"
    r"|unless\s+otherwise\s+(?:stated|specified|indicated|noted)"
    r"|for\s+the\s+purposes?\s+of\s+this"
)
_CONVENTION = _w(
    r"denoted\s+by|denotes|(?:is|are)\s+indicated\s+by|indicates|(?:is|are)\s+shown\s+(?:in|as)"
    r"|figures\s+in\s+(?:brackets|parentheses)|abbreviated\s+as|referred\s+to\s+as|hereinafter"
)
_EXAMPLE = re.compile(
    r"(?<!\w)(?:for\s+example|for\s+instance|worked\s+example|to\s+illustrate|illustrative)(?!\w)"
    r"|(?<!\w)example(?:\s+\d+)?\s*:",
    re.IGNORECASE,
)
_EG = re.compile(r"(?<!\w)e\.g\.", re.IGNORECASE)
_POINTER = _w(r"available\s+at|as\s+set\s+out\s+in\s+the|published\s+(?:on|at)|www\.[\w.-]+")
_ADMIN = _w(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|(?:tel|phone|fax)\.?:?\s*\+?\d[\d\s().-]{5,}\d"
    r"|contact\s+us|enquiries|inquiries|revision\s+history|document\s+control"
    r"|last\s+(?:revised|updated)|copyright|all\s+rights\s+reserved"
)
_COPYRIGHT = re.compile("©")
_SUMMARY_TITLES = frozenset(
    {"abstract", "summary", "executive summary", "overview", "key findings", "key points"}
    | {"highlights"}
)
_HEADING_NUMBER = re.compile(
    r"^\s*(?:(?:section|part|chapter|appendix)\s+)?(?:\d+(?:\.\d+)*|[IVXLC]+|[A-Z])[.):]?\s+",
    re.IGNORECASE,
)


def obligation(text: str) -> Match | None:
    """R-ROLE-obligation."""
    return _first(text, _OBLIGATION)


def prohibition(text: str) -> Match | None:
    """R-ROLE-prohibition."""
    return _first(text, _PROHIBITION)


def permission(text: str) -> Match | None:
    """R-ROLE-permission; bare `may` is weak."""
    return _first(text, _PERMISSION) or _first(text, _MAY, weak=True)


def condition(text: str) -> Match | None:
    """R-ROLE-condition; bare `if` is weak."""
    return _first(text, _CONDITION) or _first(text, _IF, weak=True)


def exception(text: str) -> Match | None:
    """R-ROLE-exception."""
    return _first(text, _EXCEPTION)


def definition(text: str, *, block: bool = False) -> Match | None:
    """R-ROLE-definition: a glossary block, or a definition spec 04 § 2 finds in the text."""
    term = infer_glossary_term(text) if block else None
    hits = find_definitions(text, block_term=term)
    if hits:
        return Match(hits[0].term)
    return Match(None) if block else None


def computation(text: str) -> Match | None:
    """R-ROLE-computation."""
    return _first(text, _COMPUTATION)


def method(text: str) -> Match | None:
    """R-ROLE-method."""
    return _first(text, _METHOD)


def procedure(text: str, *, marker: str | None = None, list_item: bool = False) -> Match | None:
    """R-ROLE-procedure: numbered steps, or a numbered list item that opens with a verb."""
    steps = _first(text, _STEPS)
    if steps is not None or not list_item or marker is None:
        return steps
    if _LIST_LABEL.match(marker.strip()) is None:
        return None
    offset = len(marker) if text.startswith(marker) else 0
    verb = _PROCEDURE_VERB.match(text, offset)
    if verb is None:
        return None
    return Match(Span.of(text, verb.start("verb"), verb.end("verb")))


def temporal(text: str) -> Match | None:
    """R-ROLE-temporal."""
    return _first(text, _DATE, _TEMPORAL)


def quantitative(text: str) -> Match | None:
    """R-ROLE-quantitative."""
    return _first(text, _QUANTITATIVE, _PERCENT_SIGN)


def scope(text: str) -> Match | None:
    """R-ROLE-scope."""
    return _first(text, _SCOPE)


def convention(text: str) -> Match | None:
    """R-ROLE-convention."""
    return _first(text, _CONVENTION)


def example(text: str) -> Match | None:
    """R-ROLE-example; `e.g.` is weak."""
    return _first(text, _EXAMPLE) or _first(text, _EG, weak=True)


def external_pointer(text: str) -> Match | None:
    """R-ROLE-external_pointer: a citation spec 04 § 4 finds, or a pointer phrase."""
    phrase = _first(text, _POINTER)
    cites = find_citations(text)
    if cites and (phrase is None or phrase.span is None or cites[0].span.start < phrase.span.start):
        return Match(cites[0].span)
    return phrase


def administrative(text: str) -> Match | None:
    """R-ROLE-administrative."""
    return _first(text, _ADMIN, _COPYRIGHT)


def summary_title(title: str) -> bool:
    """Whether a heading, without its number, names a summary (R-ROLE-summary)."""
    bare = _HEADING_NUMBER.sub("", title, count=1)
    return " ".join(bare.split()).rstrip(":").casefold() in _SUMMARY_TITLES


_TextRule = Callable[[str], Match | None]
_TEXT_RULES: tuple[tuple[Role, _TextRule], ...] = (
    (Role.OBLIGATION, obligation),
    (Role.PERMISSION, permission),
    (Role.PROHIBITION, prohibition),
    (Role.CONDITION, condition),
    (Role.EXCEPTION, exception),
    (Role.COMPUTATION, computation),
    (Role.METHOD, method),
    (Role.TEMPORAL, temporal),
    (Role.QUANTITATIVE, quantitative),
    (Role.SCOPE, scope),
    (Role.CONVENTION, convention),
    (Role.EXAMPLE, example),
    (Role.EXTERNAL_POINTER, external_pointer),
    (Role.ADMINISTRATIVE, administrative),
)


def roles_of(text: str, *, kind: NodeKind, marker: str | None = None) -> dict[Role, Match]:
    """Every text rule that fires on a node of this kind (summary needs the tree, so not here)."""
    if kind is NodeKind.TABLE:
        rules = [(r, f) for r, f in _TEXT_RULES if r in TABLE_ROLES]
    elif kind in TEXT_KINDS:
        rules = list(_TEXT_RULES)
    else:
        return {}
    found = {role: m for role, rule in rules if (m := rule(text)) is not None}
    if kind is NodeKind.TABLE:
        return found
    defined = definition(text, block=kind is NodeKind.DEFINITION)
    if defined is not None:
        found[Role.DEFINITION] = defined
    steps = procedure(text, marker=marker, list_item=kind is NodeKind.LIST_ITEM)
    if steps is not None:
        found[Role.PROCEDURE] = steps
    return found


def _numeric_cell(node: NodeDraft) -> Match | None:
    for start, end, cell in cell_spans(node):
        if not cell.is_header and _NUMERIC_CELL.match(cell.text):
            return Match(Span.of(node.text, start, end))
    return None


def _under_summary(draft: GraphDraft, node: NodeDraft) -> bool:
    current = node.section
    while current is not None:
        parent = draft.node(current)
        if parent.kind is NodeKind.SECTION and summary_title(parent.text):
            return True
        current = parent.section
    return False


def _add(draft: GraphDraft, node: NodeDraft, role: Role, match: Match) -> None:
    maker = Maker(actor=Actor.RULE, id=f"R-ROLE-{role.value}")
    draft.add_role(
        node.id,
        RoleDraft(
            role=role, evidence=match.span, made_by=maker, basis=Basis.EXPLICIT, weak=match.weak
        ),
        stage=STAGE,
    )


def classify(draft: GraphDraft) -> None:
    """Add every rule-made role to the draft's parts (spec 03 § 2)."""
    for node in draft.nodes_of(*TEXT_KINDS, NodeKind.TABLE):
        found = roles_of(node.text, kind=node.kind, marker=node.marker)
        if node.kind is NodeKind.TABLE and Role.QUANTITATIVE not in found:
            cell = _numeric_cell(node)
            if cell is not None:
                found[Role.QUANTITATIVE] = cell
        if node.kind is not NodeKind.TABLE and _under_summary(draft, node):
            found[Role.SUMMARY] = Match(None)
        for role in sorted(found, key=list(Role).index):
            _add(draft, node, role, found[role])
