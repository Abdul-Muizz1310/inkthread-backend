"""Definition detection (spec 04 § 2), shared with spec 03's `R-ROLE-definition`.

A glossary block's term is the start of its text. When the structure stage did not keep the term,
`infer_glossary_term` takes the text up to the first run of two or more spaces, a colon, an em or en
dash, or the word `means`, whichever comes first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from inkthread.domain.model import Span

_OPEN = "\"“'\u2018"
_CLOSE = "\"”'\u2019"
_INNER = r"[^\"“”'\u2018\u2019\n]{1,80}?"
_QUOTED_TERM = rf"[{_OPEN}](?P<term>{_INNER})[{_CLOSE}]"

_QUOTED = re.compile(
    rf"(?<!\w){_QUOTED_TERM}\s*,?\s+"
    r"(?P<cue>means|shall\s+mean|has\s+the\s+meaning|refers\s+to|is\s+defined\s+as|includes)(?!\w)",
    re.IGNORECASE,
)
_TITLE_WORD = r"(?:[A-Z][\w'\u2019&-]*|[A-Z0-9][A-Z0-9&-]*)"
_BARE = re.compile(
    rf"^\s*(?P<term>{_TITLE_WORD}(?:[ \t]+{_TITLE_WORD}){{0,5}})\s+"
    r"(?P<cue>means|shall\s+mean|is\s+defined\s+as)(?!\w)"
)
_THE_TERM = re.compile(rf"(?<!\w)(?P<cue>the\s+terms?)\s+{_QUOTED_TERM}", re.IGNORECASE)
_PARENTHETICAL = re.compile(
    r"\(\s*(?P<cue>(?:the|each\s+an?|an?|hereinafter(?:\s+referred\s+to\s+as)?)\s+)?"
    rf"{_QUOTED_TERM}\s*\)",
    re.IGNORECASE,
)
_ACRONYM = re.compile(r"\(\s*(?P<term>[A-Z][A-Za-z0-9&]*(?:[ ][A-Z][A-Za-z0-9&]*)?)\s*\)")
_TOKEN = re.compile(r"[^\s()]+")
_GLOSSARY_STOP = re.compile(r"\s{2,}|:|—|\u2013|\s+means(?!\w)")

_STOP_TERMS = frozenset({"A", "An", "The", "This", "That", "It", "I", "We", "You"})
_NO_LETTERS = frozenset({"of", "and", "for", "the", "in", "on", "&"})
_MAX_TERM = 80
_MAX_WORDS = 8
_ACRONYM_WINDOW = 12


@dataclass(frozen=True)
class DefinitionHit:
    """One definition found in a text: the term, the cue that defines it, its shape."""

    term: Span
    cue: Span | None
    shape: str
    alias: Span | None = None

    @property
    def rule(self) -> str:
        """The rule id that found it."""
        return f"R-TERM-{self.shape}"


def is_term(term: str) -> bool:
    """Spec 04 § 2: 1-80 characters, at most 8 words, not a single character or a stop word."""
    words = term.split()
    return (
        1 < len(term) <= _MAX_TERM
        and 0 < len(words) <= _MAX_WORDS
        and term.strip() == term
        and term not in _STOP_TERMS
    )


def infer_glossary_term(text: str) -> str | None:
    """The term at the start of a glossary block whose term the structure stage did not keep."""
    stop = _GLOSSARY_STOP.search(text)
    if stop is None:
        return None
    term = text[: stop.start()].strip()
    return term if is_term(term) else None


def _span(text: str, start: int, end: int) -> Span | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return Span.of(text, start, end) if end > start else None


def _hit(
    text: str, m: re.Match[str], shape: str, *, cue_group: str = "cue"
) -> DefinitionHit | None:
    term = _span(text, m.start("term"), m.end("term"))
    if term is None or not is_term(term.quote):
        return None
    cue = None
    if m.group(cue_group) is not None:
        cue = _span(text, m.start(cue_group), m.end(cue_group))
    return DefinitionHit(term=term, cue=cue, shape=shape)


def _glossary(text: str, block_term: str) -> DefinitionHit | None:
    start = text.find(block_term)
    if start < 0 or not is_term(block_term):
        return None
    return DefinitionHit(
        term=Span.of(text, start, start + len(block_term)), cue=None, shape="glossary"
    )


def _letters(word: str) -> str | None:
    """What a long-form word contributes to its acronym; None when it cannot contribute."""
    if word in _NO_LETTERS:
        return ""
    if word.isupper() and word.isalpha() and len(word) <= 4:
        return word
    if word[0].isupper():
        return word[0]
    return None


def _acronyms(text: str) -> list[DefinitionHit]:
    hits: list[DefinitionHit] = []
    for m in _ACRONYM.finditer(text):
        letters = m.group("term").replace(" ", "").replace("&", "").upper()
        tokens = list(_TOKEN.finditer(text, 0, m.start()))[-_ACRONYM_WINDOW:]
        if not tokens or text[tokens[-1].end() : m.start()].strip():
            continue
        built = ""
        for i in range(len(tokens) - 1, -1, -1):
            part = _letters(tokens[i].group())
            if part is None:
                break
            built = part + built
            if built == letters and part:
                term = Span.of(text, m.start("term"), m.end("term"))
                if is_term(term.quote):
                    alias = Span.of(text, tokens[i].start(), tokens[-1].end())
                    hits.append(DefinitionHit(term=term, cue=None, shape="acronym", alias=alias))
                break
            if not letters.endswith(built):
                break
    return hits


def find_definitions(text: str, *, block_term: str | None = None) -> list[DefinitionHit]:
    """Every definition the text states, in reading order, one per term span."""
    found: list[DefinitionHit | None] = []
    if block_term is not None:
        found.append(_glossary(text, block_term))
    found.extend(_hit(text, m, "quoted") for m in _QUOTED.finditer(text))
    found.extend(_hit(text, m, "bare") for m in _BARE.finditer(text))
    found.extend(_hit(text, m, "the-term") for m in _THE_TERM.finditer(text))
    found.extend(_hit(text, m, "parenthetical") for m in _PARENTHETICAL.finditer(text))
    found.extend(_acronyms(text))
    hits: list[DefinitionHit] = []
    for hit in found:
        if hit is None:
            continue
        if any(h.term.start < hit.term.end and hit.term.start < h.term.end for h in hits):
            continue
        hits.append(hit)
    return sorted(hits, key=lambda h: h.term.start)
