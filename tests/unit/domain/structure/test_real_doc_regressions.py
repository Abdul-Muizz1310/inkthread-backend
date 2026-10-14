"""Regressions found running the NIST AI RMF and USPTO fee schedule end to end."""

from __future__ import annotations

from readings import ReadingBuilder

from inkthread.domain.structure.setaside import set_aside
from inkthread.domain.structure.title import find_title


def test_a_two_line_title_is_one_title_and_its_repeat_opens_nothing() -> None:
    b = ReadingBuilder(pages=2)
    one = b.heading("Artificial Intelligence Risk Management", level=1)
    two = b.heading("Framework (AI RMF 1.0)", level=1)
    rep1 = b.heading("Artificial Intelligence Risk Management", level=1, page=2)
    rep2 = b.heading("Framework (AI RMF 1.0)", level=1, page=2)
    b.para("Body text.", page=2)
    r = b.build()
    t = find_title(list(r.blocks))
    assert [x.id for x in t.lines] == [one, two]
    assert t.text == "Artificial Intelligence Risk Management\nFramework (AI RMF 1.0)"
    assert {x.id for x in t.repeats} == {rep1, rep2}


def test_a_heading_below_the_first_blocks_is_not_the_title() -> None:
    b = ReadingBuilder()
    b.para("Effective January 19, 2025")
    b.para("Fees are set by rule.")
    b.para("See the tables below.")
    b.heading("Patent fees", level=1)
    assert find_title(list(b.build().blocks)).block is None


def test_a_toc_after_a_contents_heading_is_set_aside_even_with_heading_numbers() -> None:
    b = ReadingBuilder(pages=3)
    b.para(" ".join(["word"] * 45))
    contents = b.heading("Table of Contents", level=2)
    lines = [
        b.heading(t, level=3)
        for t in ("1 Framing Risk 4", "2 Audience 9", "3 Risks 12", "4 Effectiveness 19")
    ]
    for n, t in ((1, "Framing Risk"), (2, "Audience"), (3, "Risks"), (4, "Effectiveness")):
        b.heading(f"{n} {t}", level=2, number=str(n), page=2)
        b.para("Body.", page=2)
    gone = {e.block for e in set_aside(list(b.build().blocks))}
    assert {contents, *lines} <= gone


def test_fused_toc_paragraphs_and_list_headings_stay_in_the_run() -> None:
    b = ReadingBuilder(pages=2)
    b.heading("Table of Contents", level=2)
    first = b.heading("1 Framing Risk 4", level=3)
    fused = b.para(
        "1.1 Understanding Risks 4 1.2 Challenges for AI Risk Management 5 "
        "1.2.1 Risk Measurement 5 1.2.2 Risk Tolerance 7 1.2.3 Risk Prioritization 7 "
        "1.2.4 Organizational Integration 8"
    )
    lot = b.heading("List of Tables", level=2)
    tables = b.para(
        "Table 1 Categories for the GOVERN function. 22 Table 2 Categories for the "
        "MAP function. 26 Table 3 Categories for the MEASURE function. 29"
    )
    b.heading("1 Framing Risk", level=2, number="1", page=2)
    body = b.para("AI risk management is a key component of responsible development. " * 3, page=2)
    gone = {e.block for e in set_aside(list(b.build().blocks))}
    assert {first, fused, lot, tables} <= gone
    assert body not in gone


def test_a_label_repeated_on_the_cover_pages_is_furniture() -> None:
    b = ReadingBuilder(pages=3)
    cover = b.heading("NIST AI 100-1", level=4)
    b.heading("Artificial Intelligence Risk Management Framework", level=1)
    again = b.heading("NIST AI 100-1", level=2, page=2)
    b.heading("Executive Summary", level=3, page=3)
    b.para("Body.", page=3)
    entries = {e.block: e for e in set_aside(list(b.build().blocks))}
    assert {cover, again} <= set(entries)
    assert entries[cover].reason == "R-SET-cover"
    assert entries[cover].kind == "furniture"


def test_a_heading_repeated_later_in_the_body_is_kept() -> None:
    b = ReadingBuilder(pages=5)
    b.heading("Fees", level=2)
    b.para("Body.")
    keep = b.heading("Fees", level=2, page=4)
    assert keep not in {e.block for e in set_aside(list(b.build().blocks))}
