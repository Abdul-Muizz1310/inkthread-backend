"""Content-derived identifiers (spec 01 § 5).

The same document read twice gets the same ids, and a node keeps its id when an unrelated part of
the document changes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

_WS = re.compile(r"\s+")


def fold(text: str) -> str:
    """Collapse every run of Unicode whitespace to one space and strip the ends."""
    return _WS.sub(" ", text).strip()


def h(parts: Sequence[str]) -> str:
    """First 16 hex characters of sha256 over the parts joined by the unit separator."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def document_id(pdf_sha256: str) -> str:
    """The document node's id."""
    return "d:" + pdf_sha256[:16]


def section_id(ancestor_titles: Sequence[str], text: str) -> str:
    """A section's id from its ancestors' titles and its own heading text."""
    return "s:" + h(["section", *(fold(t) for t in ancestor_titles), fold(text)])


def part_id(kind: str, section_titles: Sequence[str], text: str) -> str:
    """A content part's id from its kind, its section path and its text."""
    return "p:" + h([kind, *(fold(t) for t in section_titles), fold(text)])


def term_id(key: str) -> str:
    """A defined term's id from its matching key (spec 04 § 3)."""
    return "t:" + h(["term", key])


def external_id(key: str) -> str:
    """An outside source's id from its normalised citation key (spec 04 § 4)."""
    return "x:" + h(["external", key])


def edge_id(edge_type: str, source: str, target: str, method: str, label: str | None) -> str:
    """An edge's id: one edge per (type, source, target, method, label)."""
    return "e:" + h([edge_type, source, target, method, label or ""])


class TwinRegistry:
    """Hands out `:2`, `:3` … suffixes to identical twins in the order they are claimed."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def claim(self, base: str) -> str:
        """Return `base` the first time, then `base:2`, `base:3` …"""
        count = self._seen.get(base, 0) + 1
        self._seen[base] = count
        return base if count == 1 else f"{base}:{count}"
