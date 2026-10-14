"""Spec 04 § 2-3: definitions and terms (T-LK-1…8)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from link_drafts import DraftBuilder, edges_of

from inkthread.domain.link.definitions import find_definitions, infer_glossary_term
from inkthread.domain.link.terms import TermForms, link_terms, match_terms, term_key
from inkthread.domain.model import EdgeType, FlagCode, NodeKind


@pytest.mark.parametrize(
    ("text", "term", "shape"),
    [
        ('"Micro entity" means an applicant who…', "Micro entity", "quoted"),
        ("“Micro entity” means an applicant who…", "Micro entity", "quoted"),
        ("'Business Day' shall mean any day…", "Business Day", "quoted"),
        ('"Fee" has the meaning given in the Act.', "Fee", "quoted"),
        ('"Member" refers to a firm.', "Member", "quoted"),
        ('"Order" is defined as an instruction.', "Order", "quoted"),
        ('"Fees" includes all charges.', "Fees", "quoted"),
        ("Business Day means any day on which banks open.", "Business Day", "bare"),
        ("NET VOLUME shall mean the sum of trades.", "NET VOLUME", "bare"),
        ('In this guide the term "Member" covers firms.', "Member", "the-term"),
        ("In this guide the term “Member” covers firms.", "Member", "the-term"),
        ('This agreement (the "Agreement") binds you.', "Agreement", "parenthetical"),
        ('the firm ("Firm") pays', "Firm", "parenthetical"),
        ('the firm (hereinafter "Firm") pays', "Firm", "parenthetical"),
        ('the firm (hereinafter referred to as "Firm") pays', "Firm", "parenthetical"),
        ('a member (each a "Participant") pays', "Participant", "parenthetical"),
        ('a broker (an "Agent") pays', "Agent", "parenthetical"),
        ("Artificial Intelligence (AI) is used.", "AI", "acronym"),
    ],
)
def test_t_lk_1_each_shape_finds_its_term(text: str, term: str, shape: str) -> None:
    hits = find_definitions(text)
    assert [h.shape for h in hits] == [shape]
    hit = hits[0]
    assert hit.term.quote == term
    assert text[hit.term.start : hit.term.end] == term
    assert hit.rule == f"R-TERM-{shape}"


def test_t_lk_2_acronyms() -> None:
    (ai,) = find_definitions("Artificial Intelligence (AI) is a field.")
    assert ai.term.quote == "AI"
    assert ai.alias is not None
    assert ai.alias.quote == "Artificial Intelligence"
    (rmf,) = find_definitions("The AI Risk Management Framework (AI RMF) helps.")
    assert rmf.term.quote == "AI RMF"
    assert rmf.alias is not None
    assert rmf.alias.quote == "AI Risk Management Framework"
    assert find_definitions("See the Annual Report (XYZ) for detail.") == []


def test_t_lk_3_glossary_block_defines_its_term() -> None:
    text = "Clearing Member  A member of the clearing house."
    (hit,) = find_definitions(text, block_term="Clearing Member")
    assert hit.shape == "glossary"
    assert hit.term.quote == "Clearing Member"
    assert hit.term.start == 0
    b = DraftBuilder()
    b.section("1 Definitions", "1")
    definer = b.part(text, NodeKind.DEFINITION)
    link_terms(b.draft)
    (edge,) = edges_of(b.draft, EdgeType.DEFINES)
    assert edge.source == definer
    assert edge.method == "R-TERM-glossary"
    term = b.draft.node(edge.target)
    assert term.kind is NodeKind.TERM
    assert term.text == "Clearing Member"
    assert term.section is None
    assert term.regions == []


@pytest.mark.parametrize(
    ("text", "term"),
    [
        ("Clearing Member  A member of the clearing house.", "Clearing Member"),
        ("Clearing Member: A member of the clearing house.", "Clearing Member"),
        ("Clearing Member — A member of the clearing house.", "Clearing Member"),
        ("Clearing Member \u2013 A member of the clearing house.", "Clearing Member"),
        ("Clearing Member means a member of the house.", "Clearing Member"),
    ],
)
def test_glossary_term_is_inferred_from_the_block_prefix(text: str, term: str) -> None:
    assert infer_glossary_term(text) == term


def test_glossary_without_a_separator_infers_nothing() -> None:
    assert infer_glossary_term("A plain sentence with no separator at all.") is None


def test_t_lk_4_case_and_plural() -> None:
    b = DraftBuilder()
    b.section("1 Definitions", "1")
    b.part("Business Day means any day on which banks open.")
    b.part("Member means a firm admitted to trading.")
    user = b.part("Within two business days, each of the Members files. A Member's fee is due.")
    lower = b.part("Any member of the public may watch.")
    link_terms(b.draft)
    uses = {(e.source, e.label) for e in edges_of(b.draft, EdgeType.USES_TERM)}
    assert (user, "business days") in uses
    assert (user, "Members") in uses
    assert not any(src == lower for src, _ in uses)


def test_t_lk_4_possessive_form() -> None:
    b = DraftBuilder()
    b.part("Member means a firm admitted to trading.")
    user = b.part("Each Member's fee is due.")
    link_terms(b.draft)
    (use,) = edges_of(b.draft, EdgeType.USES_TERM)
    assert (use.source, use.label) == (user, "Member's")


def test_y_plural_forms() -> None:
    forms = TermForms.of("Party")
    uses = match_terms("Both Parties sign.", [forms])
    assert [u.span.quote for u in uses] == ["Parties"]


def test_t_lk_5_longest_term_claims_first() -> None:
    b = DraftBuilder()
    b.part('"Micro Entity" means a small applicant.')
    b.part('"Micro Entity Fee" means the reduced fee.')
    user = b.part("The micro entity fee is due on filing.")
    link_terms(b.draft)
    uses = [e for e in edges_of(b.draft, EdgeType.USES_TERM) if e.source == user]
    assert len(uses) == 1
    assert b.draft.node(uses[0].target).text == "Micro Entity Fee"


def test_t_lk_6_definer_gets_defines_not_uses() -> None:
    b = DraftBuilder()
    definer = b.part('"Member" means a firm. A Member pays fees.')
    user = b.part("No fee applies. Each Member pays. Every Member files.")
    link_terms(b.draft)
    (defines,) = edges_of(b.draft, EdgeType.DEFINES)
    assert defines.source == definer
    assert defines.evidence is not None
    assert defines.evidence.quote == "Member"
    (use,) = edges_of(b.draft, EdgeType.USES_TERM)
    assert use.source == user
    assert use.method == "R-TERM-use"
    assert use.evidence is not None
    assert use.evidence.start == user_text_index(b, user, "Member")


def user_text_index(b: DraftBuilder, node_id: str, word: str) -> int:
    return b.draft.node(node_id).text.index(word)


def test_t_lk_7_two_definers_one_term() -> None:
    b = DraftBuilder()
    first = b.part('"Member" means a firm.')
    second = b.part('"Member" means a firm admitted to trading.')
    link_terms(b.draft)
    terms = b.draft.nodes_of(NodeKind.TERM)
    assert len(terms) == 1
    defines = edges_of(b.draft, EdgeType.DEFINES)
    assert {e.source for e in defines} == {first, second}
    flags = [f for f in terms[0].flags if f.code is FlagCode.MULTIPLE_DEFINITIONS]
    assert [f.detail for f in flags] == ["2"]


@pytest.mark.parametrize(
    "text",
    ['"The" means the article.', '"A" means a letter.', '"x" means a variable.', 'the term "It"'],
)
def test_t_lk_8_stop_terms_never_become_terms(text: str) -> None:
    assert find_definitions(text) == []


def test_term_nodes_follow_every_part_in_first_appearance_order() -> None:
    b = DraftBuilder()
    b.part('"Zeta" means last. "Alpha" means first.')
    b.part('"Beta" means second.')
    link_terms(b.draft)
    terms = b.draft.nodes_of(NodeKind.TERM)
    assert [t.text for t in terms] == ["Zeta", "Alpha", "Beta"]
    others = max(n.order for n in b.draft.nodes.values() if n.kind is not NodeKind.TERM)
    assert [t.order for t in terms] == [others + 1, others + 2, others + 3]
    assert terms[0].made_by.id == "R-TERM-quoted"


def test_acronym_long_form_counts_as_use() -> None:
    b = DraftBuilder()
    b.part("Artificial Intelligence (AI) is a field.")
    user = b.part("Rules on artificial intelligence apply.")
    link_terms(b.draft)
    (use,) = edges_of(b.draft, EdgeType.USES_TERM)
    assert use.source == user
    assert use.label == "artificial intelligence"
    assert b.draft.node(use.target).text == "AI"


def test_term_keys() -> None:
    assert term_key("Business  Day") == "business day"
    assert term_key("Member") == "Member"


_WORDS = st.sampled_from(["Member", "Micro", "Entity", "Fee", "fees", "day", "Day", "Party", " "])


@given(st.lists(_WORDS, max_size=30))
def test_term_matching_never_claims_characters_twice(words: list[str]) -> None:
    text = " ".join(words)
    forms = [TermForms.of(t) for t in ("Member", "Micro Entity", "Micro Entity Fee", "Fee", "Day")]
    uses = match_terms(text, forms)
    claimed: set[int] = set()
    for use in uses:
        assert use.span.fits(text)
        chars = set(range(use.span.start, use.span.end))
        assert not chars & claimed
        claimed |= chars
