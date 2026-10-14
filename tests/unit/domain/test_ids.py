"""Spec 01 § 5: content-derived identifiers (T-GC-3, T-GC-4, T-GC-6, test_ids_unicode)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from inkthread.domain.ids import (
    TwinRegistry,
    document_id,
    edge_id,
    external_id,
    fold,
    h,
    part_id,
    section_id,
    term_id,
)
from inkthread.domain.text import cut_label


def test_fold_collapses_unicode_whitespace() -> None:
    assert fold("  a\n\tb\u00a0 c ") == "a b c"


def test_h_is_16_hex() -> None:
    v = h(["a", "b"])
    assert len(v) == 16
    assert int(v, 16) >= 0
    assert h(["a", "b"]) != h(["ab"])


def test_prefixes() -> None:
    assert document_id("0" * 64) == "d:" + "0" * 16
    assert section_id([], "1 Intro").startswith("s:")
    assert part_id("paragraph", [], "x").startswith("p:")
    assert term_id("x").startswith("t:")
    assert external_id("x").startswith("x:")
    assert edge_id("contains", "a", "b", "R", None).startswith("e:")


def test_part_ids_are_stable_under_whitespace_only() -> None:  # T-GC-3
    a = part_id("paragraph", ["Fees"], "Members must  pay.")
    assert a == part_id("paragraph", ["Fees"], "Members must\npay.")
    assert a != part_id("paragraph", ["Fees"], "Members must play.")
    assert a != part_id("list_item", ["Fees"], "Members must pay.")
    assert a != part_id("paragraph", ["Other"], "Members must pay.")


def test_twins_in_reading_order() -> None:  # T-GC-4
    reg = TwinRegistry()
    base = part_id("paragraph", [], "Reserved.")
    assert [reg.claim(base) for _ in range(3)] == [base, base + ":2", base + ":3"]


def test_ids_unicode() -> None:
    assert part_id("paragraph", ["Gebühren"], "Café — 費用") == part_id(
        "paragraph", ["Gebühren"], "Café  —  費用"
    )
    assert external_id("règlement (ue) 2016/679").startswith("x:")


def test_label_cut() -> None:  # T-GC-6
    text = "word " * 40
    label, truncated = cut_label(text.strip())
    assert truncated
    assert len(label) <= 80
    assert text.startswith(label)
    assert not label.endswith(" ")
    assert cut_label("short text") == ("short text", False)


@given(st.text(max_size=300))
def test_label_is_always_a_prefix(text: str) -> None:
    label, truncated = cut_label(text)
    assert text.startswith(label)
    assert len(label) <= 80
    assert truncated == (label != text)
