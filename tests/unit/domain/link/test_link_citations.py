"""Spec 04 § 4: citations to outside sources (T-LK-9…11)."""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st
from link_drafts import DraftBuilder, edges_of

from inkthread.domain.link.citations import find_citations, link_citations
from inkthread.domain.model import EdgeType, NodeKind


@pytest.mark.parametrize(
    ("text", "printed", "key", "rule"),
    [
        ("See 37 CFR 1.27 now.", "37 CFR 1.27", "37 cfr 1.27", "R-CITE-cfr"),
        ("See 37 C.F.R. § 1.16(a) now.", "37 C.F.R. § 1.16(a)", "37 cfr 1.16(a)", "R-CITE-cfr"),
        ("See 12 CFR Part 1026 now.", "12 CFR Part 1026", "12 cfr 1026", "R-CITE-cfr"),
        ("See 35 U.S.C. 41 now.", "35 U.S.C. 41", "35 usc 41", "R-CITE-usc"),
        ("See 15 USC § 78c(a) now.", "15 USC § 78c(a)", "15 usc 78c(a)", "R-CITE-usc"),
        (
            "Under Regulation (EU) 2016/679 data",
            "Regulation (EU) 2016/679",
            "regulation (eu) 2016/679",
            "R-CITE-eu",
        ),
        (
            "Under Directive 2014/65/EU firms",
            "Directive 2014/65/EU",
            "directive 2014/65/eu",
            "R-CITE-eu",
        ),
        ("by Pub. L. 112-29 the", "Pub. L. 112-29", "public law 112-29", "R-CITE-publaw"),
        ("by Public Law 112-29 the", "Public Law 112-29", "public law 112-29", "R-CITE-publaw"),
        (
            "under the Leahy-Smith America Invents Act today",
            "the Leahy-Smith America Invents Act",
            "leahy-smith america invents act",
            "R-CITE-act",
        ),
        (
            "under the Securities Exchange Act of 1934 today",
            "the Securities Exchange Act of 1934",
            "securities exchange act of 1934",
            "R-CITE-act",
        ),
        (
            "Rule 7 of the Exchange Rules applies",
            "Exchange Rules",
            "exchange rules",
            "R-CITE-named",
        ),
        (
            "Article 2 of the FINRA By-Laws applies",
            "FINRA By-Laws",
            "finra by-laws",
            "R-CITE-named",
        ),
        (
            "per ISO/IEC 27001:2022 controls",
            "ISO/IEC 27001:2022",
            "iso/iec 27001:2022",
            "R-CITE-standard",
        ),
        ("per NIST SP 800-53 controls", "NIST SP 800-53", "nist sp 800-53", "R-CITE-standard"),
        ("per NIST AI 100-1 controls", "NIST AI 100-1", "nist ai 100-1", "R-CITE-standard"),
        ("per FIPS 140-3 controls", "FIPS 140-3", "fips 140-3", "R-CITE-standard"),
        ("per RFC 8118 controls", "RFC 8118", "rfc 8118", "R-CITE-standard"),
        ("per IEEE 754 controls", "IEEE 754", "ieee 754", "R-CITE-standard"),
        (
            "at https://example.com/fees/ today",
            "https://example.com/fees",
            "https://example.com/fees",
            "R-CITE-url",
        ),
        ("doi:10.1000/xyz123 here", "doi:10.1000/xyz123", "doi:10.1000/xyz123", "R-CITE-url"),
        ("see 10.1000/xyz123 here", "10.1000/xyz123", "10.1000/xyz123", "R-CITE-url"),
    ],
)
def test_t_lk_9_each_row_matches_and_keys(text: str, printed: str, key: str, rule: str) -> None:
    (hit,) = find_citations(text)
    assert (hit.span.quote, hit.key, hit.rule) == (printed, key, rule)
    assert hit.span.fits(text)


def test_t_lk_9_cfr_forms_share_one_external() -> None:
    b = DraftBuilder()
    first = b.part("See 37 CFR 1.27 for the rule.")
    second = b.part("Also 37 C.F.R. § 1.27 applies.")
    link_citations(b.draft)
    (external,) = b.draft.nodes_of(NodeKind.EXTERNAL)
    assert external.text == "37 CFR 1.27"
    assert external.section is None
    assert external.made_by.id == "R-CITE-cfr"
    cites = edges_of(b.draft, EdgeType.CITES_EXTERNAL)
    assert {(e.source, e.label) for e in cites} == {
        (first, "37 CFR 1.27"),
        (second, "37 C.F.R. § 1.27"),
    }
    assert all(e.target == external.id for e in cites)


def test_t_lk_10_this_act_is_not_a_citation() -> None:
    assert find_citations("This Act applies to members.") == []
    assert find_citations("Such Act applies.") == []
    (hit,) = find_citations("It falls under the Patent Act.")
    assert hit.key == "patent act"


def test_t_lk_11_url_loses_trailing_period() -> None:
    (hit,) = find_citations("Fees are at https://example.com/fees.")
    assert hit.span.quote == "https://example.com/fees"


def test_overlapping_matches_keep_longest() -> None:
    (hit,) = find_citations("See 37 C.F.R. § 1.16(a).")
    assert hit.span.quote == "37 C.F.R. § 1.16(a)"


def test_document_never_cites_itself() -> None:
    b = DraftBuilder(title="The Securities Exchange Act of 1934")
    b.part("Under the Securities Exchange Act of 1934 members file.")
    link_citations(b.draft)
    assert b.draft.nodes_of(NodeKind.EXTERNAL) == []


_PIECES = st.sampled_from(
    [
        "37 CFR 1.27",
        "the Patent Act",
        "of the Exchange Rules",
        "https://a.example/x.",
        "RFC 8118",
        "Regulation (EU) 2016/679",
        "Section 4",
        "and",
        " ",
        ",",
        "Directive 2014/65/EU",
    ]
)


@given(st.lists(_PIECES, max_size=20))
def test_find_citations_never_overlaps(pieces: list[str]) -> None:
    text = " ".join(pieces)
    hits = find_citations(text)
    for a, b in pairwise(hits):
        assert a.span.end <= b.span.start
    assert all(h.span.fits(text) for h in hits)
