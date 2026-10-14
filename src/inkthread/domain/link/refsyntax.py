"""The printed shape of a section reference (spec 04 § 5): a reference word and a list of refs."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORDS = (
    r"sections?|sec\.|clauses?|articles?|chapters?|parts?|paragraphs?|appendix|appendices"
    r"|annex(?:es)?|schedules?|exhibits?|rules?"
)
_PARENS = r"(?:\([A-Za-z0-9]{1,4}\))*"
_NUMBER = rf"\d+(?:\.\d+)*[A-Za-z]?{_PARENS}"
_LETTER = rf"[A-Z](?:\.\d+)*{_PARENS}"
_ROMAN = r"[IVXLC]+"
# A letter ref after a join must not be the article of a following phrase ("and A member").
REF_FIRST = rf"(?:{_NUMBER}|{_LETTER}|{_ROMAN})(?!\w)"
REF_NEXT = rf"(?:{_NUMBER}|{_LETTER}(?!\s+[a-z])|{_ROMAN})(?!\w)"
_JOIN = r"(?:\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or|to|through)\s+|\s*[-\u2013]\s*)"

REF_LIST = re.compile(
    rf"(?<!\w)(?:(?P<sym>§§?)\s*|(?P<word>(?i:{_WORDS}))\s+)"
    rf"(?P<refs>{REF_FIRST}(?:{_JOIN}{REF_NEXT})*)"
)
_ONE = re.compile(rf"(?P<join>{_JOIN})?(?P<ref>{REF_NEXT}|{REF_FIRST})")
_RANGE_JOIN = re.compile(r"^\s*(?:to|through|-|\u2013)\s*$", re.IGNORECASE)
_THIS = re.compile(r"(?<!\w)this\s+\Z", re.IGNORECASE)

_COUNTERS = {
    "sec": "section",
    "section": "section",
    "article": "article",
    "chapter": "chapter",
    "part": "part",
    "appendix": "appendix",
    "appendice": "appendix",
    "annex": "appendix",
    "schedule": "appendix",
    "exhibit": "appendix",
}


@dataclass(frozen=True)
class PrintedRef:
    """One ref inside a reference list: its text, where it sits, and whether a range ends at it."""

    ref: str
    start: int
    end: int
    range_end: bool


def counter_of(word: str | None) -> str:
    """The section-index counter a reference word names (`num` when it names none)."""
    if word is None:
        return "section"
    base = word.lower().rstrip(".")
    for suffix in ("es", "s"):
        stem = base.removesuffix(suffix)
        if stem in _COUNTERS:
            return _COUNTERS[stem]
    return _COUNTERS.get(base, "num")


def split_refs(text: str, m: re.Match[str]) -> list[PrintedRef]:
    """The refs of one reference-list match, with offsets into `text`."""
    refs: list[PrintedRef] = []
    pos = m.start("refs")
    end = m.end("refs")
    while pos < end:
        one = _ONE.match(text, pos, end)
        if one is None:
            break
        join = one.group("join") or ""
        refs.append(
            PrintedRef(
                ref=one.group("ref"),
                start=one.start("ref"),
                end=one.end("ref"),
                range_end=bool(refs) and _RANGE_JOIN.match(join) is not None,
            )
        )
        pos = one.end()
    return refs


def after_this(text: str, m: re.Match[str]) -> bool:
    """Whether the reference is written `this Section …`."""
    return _THIS.search(text, 0, m.start()) is not None
