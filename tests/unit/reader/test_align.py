"""Spec 02 § 1.1: words align to their block's text by a forward search from a cursor."""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st
from inkgrid import Rect

from inkthread.reader.adapt import align_words


@dataclass(frozen=True)
class FakeWord:
    """The fields alignment reads; any text, so the property can roam all of Unicode."""

    id: int
    page: int
    bbox: Rect
    text: str
    hidden: bool
    superscript: bool


def word(i: int, text: str, *, hidden: bool = False, superscript: bool = False) -> FakeWord:
    x = 72.0 + 40 * i
    return FakeWord(i, 1, Rect(x, 100.0, x + 30.0, 110.0), text, hidden, superscript)


def words_of(*texts: str) -> list[FakeWord]:
    return [word(i, t) for i, t in enumerate(texts)]


def spans(
    text: str, ws: list[FakeWord], joins: tuple[tuple[int, int], ...] = ()
) -> list[str | None]:
    return [
        None if w.start is None or w.end is None else text[w.start : w.end]
        for w in align_words(text, ws, joins)
    ]


def test_plain_words_align_in_order() -> None:
    text = "the fee is the fee"
    out = align_words(text, words_of("the", "fee", "is", "the", "fee"), ())
    assert [(w.start, w.end) for w in out] == [(0, 3), (4, 7), (8, 10), (11, 14), (15, 18)]


def test_word_carries_geometry_and_flags() -> None:
    w = word(0, "x", hidden=True, superscript=True)
    [out] = align_words("x", [w], ())
    assert (out.page, out.bbox, out.hidden, out.superscript, out.text) == (
        1,
        (72.0, 100.0, 102.0, 110.0),
        True,
        True,
        "x",
    )


def test_hyphen_join_left_word_aligns_without_hyphen() -> None:
    text = "daily settlement cycle"
    ws = words_of("daily", "settle-", "ment", "cycle")
    assert spans(text, ws, ((1, 2),)) == ["daily", "settle", "ment", "cycle"]


def test_hyphen_kept_when_not_joined() -> None:
    text = "well- known"
    assert spans(text, words_of("well-", "known"), ()) == ["well-", "known"]


def test_out_of_order_word_found_among_unclaimed_offsets() -> None:
    text = "alpha beta gamma"
    ws = words_of("beta", "gamma", "alpha")
    assert spans(text, ws, ()) == ["beta", "gamma", "alpha"]


def test_fallback_never_reuses_a_claimed_offset() -> None:
    text = "fee due"
    ws = words_of("fee", "due", "fee")
    assert spans(text, ws, ()) == ["fee", "due", None]


def test_missing_word_is_unaligned_and_text_is_unchanged() -> None:
    text = "alpha gamma"
    out = align_words(text, words_of("alpha", "beta", "gamma"), ())
    assert [(w.start, w.end) for w in out] == [(0, 5), (None, None), (6, 11)]
    assert text == "alpha gamma"


def test_table_text_with_newlines() -> None:
    text = "Service Fee\nFiling 350.00"
    assert spans(text, words_of("Service", "Fee", "Filing", "350.00"), ()) == [
        "Service",
        "Fee",
        "Filing",
        "350.00",
    ]


tokens = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Zs", "Zl", "Zp", "Cc")),
    min_size=1,
    max_size=8,
)


@given(st.lists(tokens, min_size=1, max_size=30), st.sampled_from([" ", "\n"]))
def test_every_aligned_word_slices_to_itself(toks: list[str], sep: str) -> None:
    text = sep.join(toks)
    out = align_words(text, words_of(*toks), ())
    assert len(out) == len(toks)
    for w, tok in zip(out, toks, strict=True):
        assert w.start is not None
        assert w.end is not None
        assert text[w.start : w.end] == tok
