"""Text helpers shared by the stages: labels, sentences and word-bounded search."""

from __future__ import annotations

import re
from collections.abc import Iterator

LABEL_LIMIT = 80

_ABBREVIATIONS = (
    "e.g.",
    "i.e.",
    "etc.",
    "No.",
    "no.",
    "Sec.",
    "Fig.",
    "U.S.",
    "Inc.",
    "Ltd.",
    "vs.",
    "cf.",
    "Co.",
    "Corp.",
    "Art.",
    "para.",
    "pp.",
    "p.",
)
_BOUNDARY = re.compile(r"[.;?!](?=\s+[A-Z(\"“])")


def cut_label(text: str, limit: int = LABEL_LIMIT) -> tuple[str, bool]:
    """A prefix of `text` of at most `limit` characters, cut at a word boundary when one exists.

    Returns the label and whether it is shorter than the text.
    """
    if len(text) <= limit:
        return text, False
    window = text[:limit]
    space = max(window.rfind(" "), window.rfind("\n"), window.rfind("\t"))
    label = window[:space] if space > 0 else window
    label = label.rstrip()
    if not label:
        label = window
    return label, True


def sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans `(start, end)` in `text`, per spec 04 § 1. Offsets index the original text."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.end()
        head = text[start:end]
        if head.endswith(_ABBREVIATIONS) or re.search(r"(?:^|\s)[A-Z]\.$", head):
            continue
        spans.append((start, end))
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def sentence_at(text: str, offset: int) -> tuple[int, int]:
    """The sentence span holding `offset`."""
    for start, end in sentences(text):
        if start <= offset < end:
            return start, end
    return 0, len(text)


def finditer_words(
    pattern: str, text: str, *, flags: int = re.IGNORECASE
) -> Iterator[re.Match[str]]:
    """Match `pattern` only on word boundaries (so `must` never fires inside `mustard`)."""
    return re.finditer(rf"(?<![\w]){pattern}(?![\w])", text, flags)
