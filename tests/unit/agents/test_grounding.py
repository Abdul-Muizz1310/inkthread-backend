"""Spec 05 § 4: quotes snap to the page's own words (T-AG-1..6, test_snap_unicode)."""

from __future__ import annotations

import unicodedata

from hypothesis import given
from hypothesis import strategies as st

from inkthread.agents.grounding import snap

TEXT = "Members must file the form. Members must file it again within 30 days."


def test_exact_substring_snaps_to_first_occurrence() -> None:  # T-AG-1
    span = snap(TEXT, "must file")
    assert span is not None
    assert (span.start, span.end) == (8, 17)
    assert span.quote == "must file"


def test_whitespace_differences_snap_to_original_span() -> None:  # T-AG-2
    text = "The fee is\n  calculated   monthly."
    span = snap(text, "fee is calculated monthly")
    assert span is not None
    assert span.quote == "fee is\n  calculated   monthly"
    span = snap(text, "  fee  is calculated ")
    assert span is not None
    assert span.quote == "fee is\n  calculated"


LDQ, RDQ, LSQ, RSQ, NDASH = "\u201c", "\u201d", "\u2018", "\u2019", "\u2013"
RLM, FULL_DOLLAR = "\u200f", "\uff04"


def test_curly_quotes_and_dashes_both_ways() -> None:  # T-AG-3
    text = 'The "Business Day" means Monday-Friday.'
    span = snap(text, f"{LDQ}Business Day{RDQ} means Monday{NDASH}Friday")
    assert span is not None
    assert span.quote == '"Business Day" means Monday-Friday'
    curly = f"The {LSQ}Fee{RSQ} applies 2025{NDASH}2026."
    span = snap(curly, "'Fee' applies 2025-2026")
    assert span is not None
    assert span.quote == f"{LSQ}Fee{RSQ} applies 2025{NDASH}2026"


def test_ellipsis_spans_the_gap_in_order_only() -> None:  # T-AG-4
    text = (
        "The first piece of words starts here, then a long middle that the model skipped, "
        "and the last piece of words ends it."
    )
    span = snap(text, "first piece of words ... last piece of words")
    assert span is not None
    assert span.quote.startswith("first piece of words")
    assert span.quote.endswith("last piece of words")
    assert span.quote == text[span.start : span.end]
    assert snap(text, "first piece of words … last piece of words") == span
    assert snap(text, "last piece of words ... first piece of words") is None


def test_empty_short_absent_and_case_changed_quotes_fail() -> None:  # T-AG-5
    assert snap(TEXT, "") is None
    assert snap(TEXT, "   ") is None
    assert snap(TEXT, "M") is None
    assert snap(TEXT, "pay the fee") is None
    assert snap(TEXT, "members must") is None
    assert snap(TEXT, "... ...") is None


@given(st.data())
def test_any_substring_snaps_to_itself(data: st.DataObject) -> None:  # T-AG-6
    text = data.draw(st.text(min_size=2, max_size=200))
    start = data.draw(st.integers(0, len(text) - 2))
    end = data.draw(st.integers(start + 2, len(text)))
    quote = text[start:end]
    span = snap(text, quote)
    if not quote.strip():
        assert span is None
        return
    assert span is not None
    assert span.quote == quote
    assert text[span.start : span.end] == quote


def test_snap_unicode() -> None:  # plan § Review focus 3
    text = f"Le café coûte 5 €. 会員は手数料を支払う。 {RLM}שלום עולם{RLM} fin."
    decomposed = unicodedata.normalize("NFD", "café coûte")
    span = snap(text, decomposed)
    assert span is not None
    assert span.quote == "café coûte"
    span = snap(text, "手数料を支払う")
    assert span is not None
    assert span.quote == "手数料を支払う"
    span = snap(text, "שלום עולם")
    assert span is not None
    assert text[span.start : span.end] == "שלום עולם"
    wide = snap(f"Pay {FULL_DOLLAR}5 now", "$5 now")
    assert wide is not None
    assert wide.quote == f"{FULL_DOLLAR}5 now"
