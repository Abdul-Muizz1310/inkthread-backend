"""Grounding (spec 05 § 4): a model's quote counts only when it snaps to the page's own words."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from inkthread.domain.model import Span

MIN_QUOTE = 2
MIN_PIECE = 12
# Curly, low and prime quotes fold to straight ones; dash and hyphen variants fold to "-".
_SINGLE = (0x2018, 0x2019, 0x201A, 0x201B, 0x2032)
_DOUBLE = (0x201C, 0x201D, 0x201E, 0x201F, 0x2033, 0x00AB, 0x00BB)
_QUOTES = {chr(c): "'" for c in _SINGLE} | {chr(c): '"' for c in _DOUBLE}
_DASHES = frozenset(
    chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE58, 0xFE63, 0xFF0D)
)


@dataclass(frozen=True)
class _Normal:
    """Normalised text plus, per normalised character, its original [start, end)."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


def _fold_char(char: str) -> str:
    out = []
    for c in unicodedata.normalize("NFKC", char):
        if c in _QUOTES:
            out.append(_QUOTES[c])
        elif c in _DASHES:
            out.append("-")
        else:
            out.append(c)
    return "".join(out)


def _normalise(text: str) -> _Normal:
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    i = 0
    while i < len(text):
        # Combining marks fold with their base character, so NFD input meets NFC text.
        j = i + 1
        while j < len(text) and unicodedata.combining(text[j]):
            j += 1
        folded = "".join(_fold_char(c) for c in unicodedata.normalize("NFC", text[i:j]))
        for c in folded:
            if c.isspace():
                if chars and chars[-1] == " ":
                    ends[-1] = j
                    continue
                c = " "  # noqa: PLW2901 - one space stands for the whole run
            chars.append(c)
            starts.append(i)
            ends.append(j)
        i = j
    return _Normal("".join(chars), tuple(starts), tuple(ends))


def _find(hay: _Normal, needle: str, offset: int = 0) -> tuple[int, int] | None:
    at = hay.text.find(needle, offset)
    if at < 0:
        return None
    return at, at + len(needle)


def snap(text: str, quote: str) -> Span | None:
    """The span of `text` that `quote` stands for, or None when it does not snap."""
    if len(quote) < MIN_QUOTE or not quote.strip():
        return None
    exact = text.find(quote)
    if exact >= 0:
        return Span.of(text, exact, exact + len(quote))
    hay = _normalise(text)
    needle = _normalise(quote).text.strip()
    if not needle:
        return None
    hit = _find(hay, needle)
    if hit is not None:
        return _span(text, hay, hit[0], hit[1])
    if "..." not in needle:
        return None
    pieces = [p.strip() for p in needle.split("...")]
    pieces = [p for p in pieces if len(p) >= MIN_PIECE]
    if not pieces:
        return None
    first: int | None = None
    cursor = 0
    last_end = 0
    for piece in pieces:
        found = _find(hay, piece, cursor)
        if found is None:
            return None
        if first is None:
            first = found[0]
        cursor = last_end = found[1]
    assert first is not None  # noqa: S101 - pieces is non-empty
    return _span(text, hay, first, last_end)


def _span(text: str, hay: _Normal, start: int, end: int) -> Span | None:
    lo, hi = hay.starts[start], hay.ends[end - 1]
    while lo < hi and text[lo].isspace():
        lo += 1
    while hi > lo and text[hi - 1].isspace():
        hi -= 1
    if hi - lo < 1:
        return None
    return Span.of(text, lo, hi)
