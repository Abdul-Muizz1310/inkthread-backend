"""Spec 03: rule-made roles and the residual (T-CL-1…24)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from link_drafts import DraftBuilder

from inkthread.domain.classify.residual import residual
from inkthread.domain.classify.rules import classify, roles_of
from inkthread.domain.draft import RoleDraft
from inkthread.domain.model import Actor, Basis, NodeKind, Role


def _roles(
    text: str, kind: NodeKind = NodeKind.PARAGRAPH, marker: str | None = None
) -> dict[Role, RoleDraft]:
    b = DraftBuilder()
    node = b.part(text, kind, marker=marker)
    classify(b.draft)
    return b.draft.node(node).roles


def _cue(roles: dict[Role, RoleDraft], role: Role) -> str | None:
    evidence = roles[role].evidence
    return evidence.quote if evidence else None


def test_t_cl_1_obligation() -> None:
    roles = _roles("Members must file the form.")
    assert _cue(roles, Role.OBLIGATION) == "must"
    made = roles[Role.OBLIGATION]
    assert made.basis is Basis.EXPLICIT
    assert made.made_by.actor is Actor.RULE
    assert made.made_by.id == "R-ROLE-obligation"
    assert not made.weak


def test_t_cl_2_prohibition_not_obligation() -> None:
    roles = _roles("Members must not file twice.")
    assert _cue(roles, Role.PROHIBITION) == "must not"
    assert Role.OBLIGATION not in roles


def test_t_cl_3_shall_mean_is_definition_not_obligation() -> None:
    roles = _roles("'Business Day' shall mean any day on which banks open.")
    assert Role.DEFINITION in roles
    assert Role.OBLIGATION not in roles


def test_definition_block_is_a_definition() -> None:
    roles = _roles("Clearing Member  A member of the clearing house.", NodeKind.DEFINITION)
    assert _cue(roles, Role.DEFINITION) == "Clearing Member"


def test_t_cl_4_permission_weak_and_may_vary() -> None:
    roles = _roles("Applicants may request a refund.")
    assert roles[Role.PERMISSION].weak
    assert _cue(roles, Role.PERMISSION) == "may"
    assert _roles("Results may vary.") == {}
    strong = _roles("Members are entitled to a refund.")
    assert not strong[Role.PERMISSION].weak


def test_t_cl_5_condition_strong_and_weak() -> None:
    strong = _roles("Provided that the applicant qualifies, the fee is waived.")
    assert not strong[Role.CONDITION].weak
    assert _cue(strong, Role.CONDITION) == "Provided that"
    weak = _roles("If filed late, nothing happens.")
    assert weak[Role.CONDITION].weak


def test_t_cl_6_exception() -> None:
    assert _cue(_roles("Notwithstanding Section 4, the fee is due."), Role.EXCEPTION) == (
        "Notwithstanding"
    )


def test_t_cl_7_computation() -> None:
    roles = _roles("The fee is calculated as the greater of two amounts.")
    assert _cue(roles, Role.COMPUTATION) == "calculated"


def test_t_cl_8_method() -> None:
    assert _cue(_roles("Volume is measured on a monthly basis."), Role.METHOD) == "measured"


def test_t_cl_9_procedure_needs_a_numbered_item() -> None:
    numbered = _roles("Submit the form.", NodeKind.LIST_ITEM, marker="1.")
    assert Role.PROCEDURE in numbered
    assert _roles("Submit the form.", NodeKind.LIST_ITEM, marker="•") == {}
    assert Role.PROCEDURE in _roles("Step 2 is to wait.")


def test_t_cl_10_temporal() -> None:
    assert Role.TEMPORAL in _roles("Effective January 19, 2025")
    for text in ("Due 19 January 2025.", "Due 2025-01-19.", "Due 1/19/2025."):
        assert Role.TEMPORAL in _roles(text)
    assert Role.TEMPORAL not in _roles("Section 2.1.10")


@pytest.mark.parametrize("text", ["$350.00", "0.13 EUR", "2.5%", "15 bps", "3 basis points"])
def test_t_cl_11_quantitative(text: str) -> None:
    assert _cue(_roles(f"The fee is {text} each."), Role.QUANTITATIVE) == text


def test_t_cl_12_tables_get_only_figures_and_dates() -> None:
    b = DraftBuilder()
    numeric = b.table([["Fee", "Amount"], ["Filing", "350"]])
    words = b.table([["Fee", "Note"], ["Filing", "Members must pay"]])
    classify(b.draft)
    assert set(b.draft.node(numeric).roles) == {Role.QUANTITATIVE}
    assert _cue(b.draft.node(numeric).roles, Role.QUANTITATIVE) == "350"
    assert b.draft.node(words).roles == {}


def test_t_cl_13_scope() -> None:
    assert Role.SCOPE in _roles("This section applies to all members.")


def test_t_cl_14_convention() -> None:
    roles = _roles("Figures in parentheses denote rebates.")
    assert _cue(roles, Role.CONVENTION) == "Figures in parentheses"


def test_t_cl_15_example_strong_and_weak() -> None:
    strong = _roles("For example, a member that files late pays.")
    assert not strong[Role.EXAMPLE].weak
    weak = _roles("Any institution (e.g., a bank) pays.")
    assert weak[Role.EXAMPLE].weak
    assert _cue(weak, Role.EXAMPLE) == "e.g."


def test_t_cl_16_external_pointer() -> None:
    assert _cue(_roles("See 37 CFR 1.27."), Role.EXTERNAL_POINTER) == "37 CFR 1.27"
    assert Role.EXTERNAL_POINTER in _roles("The form is available at our office.")


def test_t_cl_17_administrative() -> None:
    assert _cue(_roles("Contact fees@example.com"), Role.ADMINISTRATIVE) == "fees@example.com"
    assert Role.ADMINISTRATIVE in _roles("©2025 Example Ltd.")
    assert Role.ADMINISTRATIVE in _roles("Tel: +1 (555) 010-2000")


def test_t_cl_18_summary_from_an_ancestor_heading() -> None:
    b = DraftBuilder()
    top = b.section("1. Executive Summary", "1")
    b.section("1.1 Background", "1.1", parent=top)
    node = b.part("The program grew last year.")
    other = b.part("Nothing here.", section=b.doc)
    classify(b.draft)
    roles = b.draft.node(node).roles
    assert roles[Role.SUMMARY].evidence is None
    assert roles[Role.SUMMARY].made_by.id == "R-ROLE-summary"
    assert Role.SUMMARY not in b.draft.node(other).roles


def test_t_cl_19_four_rules_four_cues() -> None:
    roles = _roles("Members must pay $350 within 30 days unless exempt.")
    assert _cue(roles, Role.OBLIGATION) == "must"
    assert _cue(roles, Role.QUANTITATIVE) == "$350"
    assert _cue(roles, Role.TEMPORAL) == "within 30 days"
    assert _cue(roles, Role.EXCEPTION) == "unless"


_WORDS = st.sampled_from(
    [
        "must",
        "shall",
        "not",
        "may",
        "request",
        "if",
        "e.g.",
        "$350",
        "2.5%",
        "provided",
        "that",
        "notwithstanding",
        "Section",
        "4",
        "37 CFR 1.27",
        "calculated",
        "for",
        "example",
        "January 19, 2025",
        "fees@example.com",
        "mustard",
        "mean",
        "©",
        "is",
        "required",
        "to",
    ]
)


@given(st.lists(_WORDS, min_size=1, max_size=25), st.sampled_from(list(NodeKind)))
def test_t_cl_20_evidence_always_fits(words: list[str], kind: NodeKind) -> None:
    text = " ".join(words)
    for role, match in roles_of(text, kind=kind, marker="1.").items():
        assert isinstance(role, Role)
        if match.span is not None:
            assert text[match.span.start : match.span.end] == match.span.quote


def test_t_cl_21_residual_in_reading_order() -> None:
    b = DraftBuilder()
    first = b.part("A long paragraph that says nothing in particular at all, really.")
    b.part("Members must file the form before anything else happens here.")
    second = b.part(
        "Another rather long paragraph that also says nothing in particular.", NodeKind.NOTE
    )
    b.table([["Fee", "Note"], ["Filing", "nothing in particular to see in this table"]])
    classify(b.draft)
    assert residual(b.draft) == [first, second]


@pytest.mark.parametrize("text", ["mustard", "mayor", "shallow", "iffy"])
def test_t_cl_22_word_boundaries(text: str) -> None:
    assert _roles(f"The {text} plan.") == {}


def test_t_cl_23_sections_terms_externals_get_no_roles() -> None:
    b = DraftBuilder()
    section = b.section("Members must pay", "1")
    classify(b.draft)
    assert b.draft.node(section).roles == {}
    assert roles_of("Members must pay", kind=NodeKind.TERM) == {}
    assert roles_of("Members must pay", kind=NodeKind.EXTERNAL) == {}


def test_t_cl_24_short_or_hidden_paragraphs_are_not_residual() -> None:
    b = DraftBuilder()
    b.part("x" * 39)
    hidden = "y" * 50
    b.part(hidden, hidden=((0, 50),))
    b.part("z" * 10 + " " * 40)
    classify(b.draft)
    assert residual(b.draft) == []
