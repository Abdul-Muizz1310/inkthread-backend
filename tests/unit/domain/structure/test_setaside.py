"""Spec 02 § 2: set-aside (T-ST-5..9)."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.structure.setaside import set_aside

LONG = " ".join(["word"] * 45) + "."


def aside(b: ReadingBuilder) -> dict[str, str]:
    return {e.block: e.reason for e in set_aside(b.build().blocks)}


def test_furniture_is_set_aside_and_nothing_else() -> None:  # T-ST-5
    b = ReadingBuilder(pages=2)
    f1 = b.furniture("ACME Rules", role="header")
    b.heading("1 Fees", number="1")
    b.para("Members must pay the fee.")
    f2 = b.furniture("Page 2", role="footer", page=2)
    entries = set_aside(b.build().blocks)
    assert [(e.block, e.kind, e.reason) for e in entries] == [
        (f1, "furniture", "R-SET-furniture"),
        (f2, "furniture", "R-SET-furniture"),
    ]
    assert entries[1].page == 2
    assert entries[0].text == "ACME Rules"


def test_contents_heading_and_five_lines_are_set_aside() -> None:  # T-ST-6
    b = ReadingBuilder()
    h = b.heading("Contents", level=2)
    lines = [b.para(f"Chapter {n} ........ {n * 3}") for n in range(1, 6)]
    b.heading("1 Introduction", number="1", level=2, page=1)
    got = aside(b)
    assert got == dict.fromkeys([h, *lines], "R-SET-toc")


def test_two_lines_need_a_toc_heading() -> None:  # T-ST-7
    b = ReadingBuilder()
    h = b.heading("Table of Contents", level=2)
    l1 = b.para("Scope ..... 3")
    l2 = b.para("Fees ..... iv")
    b.para("The rules apply to members.")
    assert aside(b) == {h: "R-SET-toc", l1: "R-SET-toc", l2: "R-SET-toc"}

    plain = ReadingBuilder()
    plain.heading("Overview", level=2)
    plain.para("Scope ..... 3")
    plain.para("Fees ..... 4")
    assert aside(plain) == {}


def test_modal_verb_breaks_a_toc_run() -> None:  # T-ST-8
    b = ReadingBuilder()
    b.para("Fees 3")
    b.para("Members must pay 5")
    b.para("Scope 4")
    b.para("Terms 7")
    assert aside(b) == {}


def test_keep_guard_keeps_a_numbered_body_list() -> None:  # T-ST-9
    b = ReadingBuilder()
    b.para(LONG)
    b.item("See the fees in 1", label="a")
    b.item("See the scope in 2", label="b")
    b.item("See the terms in 3", label="c")
    for n in ("1", "2", "3"):
        b.heading(f"{n} Part", number=n, level=2)
        b.para("Body text.")
    assert aside(b) == {}


def test_same_list_before_any_long_paragraph_is_a_toc() -> None:
    b = ReadingBuilder(pages=2)
    lines = [b.para(f"Part {n} {n}") for n in ("1", "2", "3")]
    for n in ("1", "2", "3"):
        b.heading(f"{n} Part", number=n, level=2, page=2)
        b.para(LONG, page=2)
    assert aside(b) == dict.fromkeys(lines, "R-SET-toc")


def test_long_lines_are_not_toc_lines() -> None:
    b = ReadingBuilder()
    for n in range(3):
        b.para("x" * 170 + f" {n + 1}")
    assert aside(b) == {}
